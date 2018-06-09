import cgi
import codecs
from io import BytesIO
import logging
import types

from django.http import HttpRequest, parse_cookie, QueryDict
from django.utils.functional import cached_property
from django.conf import settings
from django.db import connections, transaction
from django.urls import get_resolver, set_urlconf
from django.utils.log import log_response

from .exception import response_for_exception

logger = logging.getLogger('django.request')


class ASGIRequest(HttpRequest):

    body_receive_timeout = 60

    def __init__(self, scope):
        self.scope = scope
        self._content_length = 0
        self._post_parse_error = False
        self._read_started = False
        self._stream = BytesIO()
        self._validate_host()
        self.META = {
            'REQUEST_METHOD': self.method,
            'QUERY_STRING': self.query_string,
            'SCRIPT_NAME': self.root_path,
            'PATH_INFO': self.path_info,
        }
        if self.scope.get('client', None):
            self.META['REMOTE_ADDR'] = self.client_host
            self.META['REMOTE_HOST'] = self.META['REMOTE_ADDR']
            self.META['REMOTE_PORT'] = self.client_port
        if self.scope.get('server', None):
            self.META['SERVER_NAME'] = self.server_host
            self.META['SERVER_PORT'] = self.server_port
        else:
            self.META['SERVER_NAME'] = 'unknown'
            self.META['SERVER_PORT'] = '0'

        for name, value in self.headers.items():
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
        return parse_cookie(self.headers.get('cookie'))


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
        response = await self.get_response(request)

        await self.send_headers(status=response.status_code, headers=response.headers)
        await self.send_body(body=response.content)

    def make_view_atomic(self, view):
        non_atomic_requests = getattr(view, '_non_atomic_requests', set())
        for db in connections.all():
            if db.settings_dict['ATOMIC_REQUESTS'] and db.alias not in non_atomic_requests:
                view = transaction.atomic(using=db.alias)(view)
        return view

    async def get_response(self, request):
        set_urlconf(settings.ROOT_URLCONF)

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
            set_urlconf(urlconf)
            resolver = get_resolver(urlconf)
        else:
            resolver = get_resolver()

        resolver_match = resolver.resolve(request.path_info)
        callback, callback_args, callback_kwargs = resolver_match
        request.resolver_match = resolver_match

        if response is None:
            wrapped_callback = self.make_view_atomic(callback)
            try:
                response = wrapped_callback(request, *callback_args, **callback_kwargs)
            except Exception as e:
                response = self.process_exception_by_middleware(e, request)

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

    def process_exception_by_middleware(self, exception, request):
        """
        Pass the exception to the exception middleware. If no middleware
        return a response for this exception, raise it.
        """
        for middleware_method in self._exception_middleware:
            response = middleware_method(request, exception)
            if response:
                return response
        raise

    async def send_headers(self, status=200, headers=[[b'content-type', b'text/plain']]):
        await self.send({
            'type': 'http.response.start',
            'status': status,
            'headers': headers
        })

    async def send_body(self, body, more_body=False):
        await self.send({
            'type': 'http.response.body',
            'body': body,
            'more_body': more_body
        })
