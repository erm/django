import cgi
import codecs
from io import BytesIO
import logging
import types

from django.http import HttpRequest, parse_cookie, QueryDict
from django.utils.functional import cached_property
from django.urls import get_resolver
from django.utils.log import log_response

from .exception import response_for_exception

logger = logging.getLogger('django.request')


class ASGIRequest(HttpRequest):

    def __init__(self, scope):
        self.scope = scope
        self.method = scope['method']
        self.query_string = self.scope.get('query_string', '')
        self._content_length = 0
        self._post_parse_error = False
        self._read_started = False
        self._stream = BytesIO()

        self.path = self.scope['path']
        if not self.path.endswith('/'):
            self.path += '/'

        script_name = self.scope.get('root_path', '')

        if script_name and self.path.startswith(script_name):
            self.path_info = self.path[len(script_name):]
        else:
            self.path_info = self.path

        self.META = {
            'REQUEST_METHOD': self.scope['method'],
            'QUERY_STRING': self.query_string,
            'SCRIPT_NAME': script_name,
            'PATH_INFO': self.path_info,
        }

        client = self.scope.get('client', None)

        if client is not None:
            remote_addr, remote_port = client
            self.META['REMOTE_ADDR'] = remote_addr
            self.META['REMOTE_HOST'] = remote_addr
            self.META['REMOTE_PORT'] = remote_port

        server = self.scope.get('server', None)
        if server is not None:
            server_name, server_port = server
        else:
            server_name, server_port = 'unknown', '0'
        self.META['SERVER_NAME'] = server_name
        self.META['SERVER_PORT'] = server_port

        for k, v in self.scope.get('headers', []):
            name, value = k.decode('ascii'), v.decode('ascii')
            if name == 'content-length':
                corrected_name = 'CONTENT_LENGTH'
            elif name == 'content-type':
                corrected_name = 'CONTENT_TYPE'
            else:
                corrected_name = 'HTTP_%s' % name.upper().replace('-', '_')
            if corrected_name in self.META:
                value = self.META[corrected_name] + ',' + value
            self.META[corrected_name] = value

        if 'CONTENT_TYPE' in self.META:
            self.content_type, self.content_params = cgi.parse_header(
                self.META['CONTENT_TYPE'])
            if 'charset' in self.content_params:
                try:
                    codecs.lookup(self.content_params['charset'])
                except LookupError:
                    pass
                else:
                    self.encoding = self.content_params['charset']
        else:
            self.content_type, self.content_params = '', {}
        # Pull out content length info
        if self.META.get('CONTENT_LENGTH', None):
            try:
                self._content_length = int(self.META['CONTENT_LENGTH'])
            except (ValueError, TypeError):
                pass

        self.resolver_match = None

    @cached_property
    def GET(self):
        return QueryDict(self.query_string)

    def _get_post(self):
        if not hasattr(self, '_post'):
            self._read_started = False
            self._load_post_and_files()
        return self._post

    def _set_post(self, post):
        self._post = post

    def _get_files(self):
        if not hasattr(self, '_files'):
            self._read_started = False
            self._load_post_and_files()
        return self._files

    POST = property(_get_post, _set_post)
    FILES = property(_get_files)

    @cached_property
    def COOKIES(self):
        return parse_cookie(self.META.get('HTTP_COOKIE', ''))

    # async def stream(self):
    #     if hasattr(self, "_body"):
    #         yield self._body
    #     return

    # async def body(self):
    #     if not hasattr(self, "_body"):
    #         body = b""
    #         async for chunk in self.stream():
    #             body += chunk
    #         self._body = body

    #     return self._body

    # @property
    # def body(self):
    #     if not hasattr(self, '_body'):
    #         if self._read_started:
    #             raise RawPostDataException("You cannot access body after reading from request's data stream")

    #         # Limit the maximum request data size that will be handled in-memory.
    #         if (settings.DATA_UPLOAD_MAX_MEMORY_SIZE is not None and
    #                 int(self.META.get('CONTENT_LENGTH') or 0) > settings.DATA_UPLOAD_MAX_MEMORY_SIZE):
    #             raise RequestDataTooBig('Request body exceeded settings.DATA_UPLOAD_MAX_MEMORY_SIZE.')

    #         try:
    #             self._body = self.read()
    #         except IOError as e:
    #             raise UnreadablePostError(*e.args) from e
    #         self._stream = BytesIO(self._body)
    #     return self._body


class ASGIHandler:

    def __call__(self, scope):
        return ASGIHandlerInstance(scope)


class ASGIHandlerInstance:

    def __init__(self, scope):
        if scope['type'] != 'http':
            raise ValueError(
                'The ASGIHandlerInstance can only handle HTTP connections, not %s' % scope['type'])
        self.scope = scope

    async def __call__(self, receive, send):
        self.send = send

        request = ASGIRequest(self.scope)
        # request.body()
        response = await self.get_response(request)

        await self.send({
            'type': 'http.response.start',
            'status': response.status_code,
            'headers': response.headers
        })

        await self.send({
            'type': 'http.response.body',
            'body': response.content,
            'more_body': False
        })

    # def make_view_atomic(self, view):
    #     non_atomic_requests = getattr(view, '_non_atomic_requests', set())
    #     for db in connections.all():
    #         if db.settings_dict['ATOMIC_REQUESTS'] and db.alias not in non_atomic_requests:
    #             view = transaction.atomic(using=db.alias)(view)
    #     return view

    async def get_response(self, request):
        try:
            response = await self._get_response(request)
        except Exception as exc:
            response = response_for_exception(request, exc)

        if not getattr(response, 'is_rendered', True) and callable(getattr(response, 'render', None)):
            response = response.render()

        if response.status_code >= 400:
            log_response(
                '%s: %s', response.reason_phrase, request.path,
                response=response,
                request=request,
            )

        return response

    async def _get_response(self, request):
        response = None

        if hasattr(request, 'urlconf'):
            urlconf = request.urlconf
            # set_urlconf(urlconf)
            resolver = get_resolver(urlconf)
        else:
            resolver = get_resolver()

        resolver_match = resolver.resolve(request.path_info)
        callback, callback_args, callback_kwargs = resolver_match
        request.resolver_match = resolver_match

        if response is None:
            # wrapped_callback = self.make_view_atomic(callback)
            try:
                response = await callback(request, *callback_args, **callback_kwargs)
            except Exception as e:
                return response_for_exception(request, e)

        # Complain if the view returned None (a common error).
        if response is None:
            if isinstance(callback, types.FunctionType):    # FBV
                view_name = callback.__name__
            else:                                           # CBV
                view_name = callback.__class__.__name__ + '.__call__'

            raise ValueError(
                "The view %s.%s didn't return an HttpResponse object. It "
                "returned None instead." % (callback.__module__, view_name)
            )
        return response
