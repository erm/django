import cgi
import codecs
from io import BytesIO


from django.core.handlers import base
from django.http import HttpRequest, parse_cookie, QueryDict
from django.utils.functional import cached_property


class ASGIRequest(HttpRequest):

    body_receive_timeout = 60

    def __init__(self, scope):
        self.scope = scope
        self._content_length = 0
        self._post_parse_error = False
        self._read_started = False
        self._stream = BytesIO()
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
            self.content_type, self.content_params = cgi.parse_header(self.META['CONTENT_TYPE'])
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


class ASGIHandler(base.BaseHandler):

    request_class = ASGIRequest

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.load_middleware()

    def __call__(self, scope):
        # signals.request_started.send(sender=self.__class__, environ=environ)
        request = self.request_class(scope)
        response = self.get_response(request)
        response._handler_class = self.__class__
        # status = '%d %s' % (response.status_code, response.reason_phrase)
        response_headers = list(response.items())
        for c in response.cookies.values():
            response_headers.append(('Set-Cookie', c.output(header='')))

        # if getattr(response, 'file_to_stream', None) is not None and environ.get('wsgi.file_wrapper'):
        #     response = environ['wsgi.file_wrapper'](response.file_to_stream)
        return ASGIHandlerInstance(scope, request=request, response=response)


class ASGIHandlerInstance:

    def __init__(self, scope, request=None, response=None):
        if scope['type'] != 'http':
            raise ValueError(
                'The ASGIHandlerInstance can only handle HTTP connections, not %s' % scope['type'])
        self.scope = scope
        self.response = response

    async def __call__(self, receive, send):
        self.send = send
        await self.send_headers(status=self.response.status_code, headers=self.response.headers)
        await self.send_body(body=self.response.content)

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
