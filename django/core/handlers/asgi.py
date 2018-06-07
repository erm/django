import cgi
import codecs
from io import BytesIO


from django.core.handlers import base
from django.http import HttpRequest, parse_cookie, QueryDict
from django.utils.functional import cached_property


class ASGIHttpRequest(HttpRequest):

    body_receive_timeout = 60

    def __init__(self, scope, body=None):
        self.scope = scope
        self._content_length = 0
        self._post_parse_error = False
        self._read_started = False
        self.resolver_match = None
        self.path = self.scope['path']
        self.script_name = self.scope.get('root_path', '')

        if self.script_name and self.path.startswith(self.script_name):
            self.path_info = self.path[len(self.script_name):]
        else:
            self.path_info = self.path

        self.method = self.scope['method'].upper()
        query_string = self.scope.get('query_string', b'')

        self.META = {
            'REQUEST_METHOD': self.method,
            'QUERY_STRING': query_string,
            'SCRIPT_NAME': self.script_name,
            'PATH_INFO': self.path_info,
        }

        if self.scope.get('client', None):
            self.META['REMOTE_ADDR'] = self.scope['client'][0]
            self.META['REMOTE_HOST'] = self.META['REMOTE_ADDR']
            self.META['REMOTE_PORT'] = self.scope['client'][1]
        if self.scope.get('server', None):
            self.META['SERVER_NAME'] = self.scope['server'][0]
            self.META['SERVER_PORT'] = str(self.scope['server'][1])
        else:
            self.META['SERVER_NAME'] = 'unknown'
            self.META['SERVER_PORT'] = '0'

        for name, value in self.scope.get('headers', []):
            name = name.decode('latin1')
            if name == 'content-length':
                corrected_name = 'CONTENT_LENGTH'
            elif name == 'content-type':
                corrected_name = 'CONTENT_TYPE'
            else:
                corrected_name = 'HTTP_%s' % name.upper().replace('-', '_')
            # HTTPbis say only ASCII chars are allowed in headers, but we latin1 just in case
            value = value.decode('latin1')
            if corrected_name in self.META:
                value = self.META[corrected_name] + ',' + value
            self.META[corrected_name] = value
        # Pull out request encoding if we find it
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
        # # Body handling
        # # TODO: chunked bodies
        # self._body = body
        # assert isinstance(self._body, bytes), 'Body is not bytes'
        # # Add a stream-a-like for the body
        # self._stream = BytesIO(self._body)
        # # Other bits
        self.resolver_match = None

    @cached_property
    def GET(self):
        return QueryDict(self.scope.get('query_string', ''))

    def _get_scheme(self):
        return self.scope.get('scheme', 'http')

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


class ASGIHandler:

    def __call__(self, scope):
        return ASGIHandlerInstance(scope)


class ASGIHandlerInstance(base.BaseHandler):

    request_class = ASGIHttpRequest

    def __init__(self, scope):
        if scope['type'] != 'http':
            raise ValueError(
                'The ASGIHandlerInstance can only handle HTTP connections, not %s' % scope['type'])
        super().__init__()
        self.scope = scope
        self.request = self.request_class(scope)
        self.load_middleware()

    async def __call__(self, receive, send):
        self.send = send
        # body = b''
        # while True:
        #     message = await receive()
        #     if message['type'] == 'http.disconnect':
        #         return
        #     else:
        #         if 'body' in message:
        #             body += message['body']
        #         if not message.get('more_body', False):
        #             # await self.send_response(body)
        #             return

        #request = self.request_class(self.scope)
        response = self.get_response(self.request)
        await response(receive, send)
        await self.send_response(response, body=b'sfs')

    async def send_response(self, response, body, more_body=False):
        print(response)

        await self.send_headers(status=response.status_code, headers=response.headers)
        await self.send_body(body=response.content, more_body=more_body)

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
