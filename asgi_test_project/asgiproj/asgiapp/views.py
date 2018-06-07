from django.views.generic import TemplateView, View
from django.http.response import HttpResponse
from django.core.handlers.asgi import ASGIHttpRequest
from functools import partial


class TestView(TemplateView):

    template_name = "index.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["context_test"] = "Hello context test."
        return context


class ASGIHttpResponse:

    def __init__(self, scope, *args, request=None, response=None, **kwargs):
        if scope["type"] != "http":
            raise ValueError(
                "The ASGIHttpResponse can only handle HTTP connections, not %s"
                % scope["type"]
            )
        self.scope = scope
        self.response = response(request, *args, **kwargs)

    async def __call__(self, receive, send):
        self.send = send
        body = b""
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            else:
                if "body" in message:
                    body += message["body"]
                if not message.get("more_body", False):
                    await self.send_response(body)
                    return

    async def send_response(self, body, more_body=False):

        request = self.request_class(self.scope, body)
        response = self.get_response(request)

        await self.send_headers(status=response.status_code, headers=response.headers)
        await self.send_body(body=response.content, more_body=more_body)

    async def send_headers(
        self, status=200, headers=[[b"content-type", b"text/plain"]]
    ):
        await self.send(
            {"type": "http.response.start", "status": status, "headers": headers}
        )

    async def send_body(self, body, more_body=False):
        await self.send(
            {"type": "http.response.body", "body": body, "more_body": more_body}
        )


class TestAsyncView(View):

    async def get(self, request, *args, **kwargs):
        print("OOOII")
        content = "Testing async"
        from pprint import pprint
        pprint(request)
        pprint(request.__dict__)
        return partial(HttpResponse, content)

    # def get(self, request, *args, **kwargs):
    #     async

    #     async def http_response(scope):
    #         content = "Testing async"
    #         return ASGIHttpResponse(content=content)

    # async def handle_response(self):
    #     if self.request.method == "HEAD":
    #         _method = "GET"
    #     else:
    #         _method = self.request.method
    #     method_handler = getattr(self, _method.lower(), None)
    #     if method_handler is None:
    #         raise Exception("Method %s is not implemented for this response." % _method)
    #     await method_handler()
