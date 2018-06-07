"""
Clickjacking Protection Middleware.

This module provides a middleware that implements protection against a
malicious site loading resources from your site in a hidden frame.
"""
from functools import partial
from traceback import format_tb

from django.conf import settings
from django.utils.deprecation import MiddlewareMixin


class XFrameOptionsMiddleware(MiddlewareMixin):
    """
    Set the X-Frame-Options HTTP header in HTTP responses.

    Do not set the header if it's already set or if the response contains
    a xframe_options_exempt value set to True.

    By default, set the X-Frame-Options header to 'SAMEORIGIN', meaning the
    response can only be loaded on a frame within the same site. To prevent the
    response from being loaded in a frame in any site, set X_FRAME_OPTIONS in
    your project's Django settings to 'DENY'.
    """
    def process_response(self, request, response):
        # Don't set it if it's already in the response
        if response.get('X-Frame-Options') is not None:
            return response

        # Don't set it if they used @xframe_options_exempt
        if getattr(response, 'xframe_options_exempt', False):
            return response

        response['X-Frame-Options'] = self.get_xframe_options_value(request,
                                                                    response)
        return response

    def get_xframe_options_value(self, request, response):
        """
        Get the value to set for the X_FRAME_OPTIONS header. Use the value from
        the X_FRAME_OPTIONS setting, or 'SAMEORIGIN' if not set.

        This method can be overridden if needed, allowing it to vary based on
        the request or response.
        """
        return getattr(settings, 'X_FRAME_OPTIONS', 'SAMEORIGIN').upper()


class XFrameOptionsASGIMiddleware(MiddlewareMixin):

    # def __init__(self, inner):
    #     """Creates a middleware instance for an uninstantiated ASGI application."""
    #     self.inner = inner

    def __call__(self, request):
        """
        Copies the incoming request scope and handles synchronous ASGI operations.
        Instantiates the inner application and partially binds it to ASGI coroutine
        entrypoint :meth:`asgi_callable` along with the scope.
        """
        scope = request.scope
        self.populate_scope(scope)

    def populate_scope(self, scope):
        """Allows modification of the scope prior application instantiation."""
        print("scoooopeeeeee")

    #     # Don't set it if it's already in the response
    #     if response.get('X-Frame-Options') is not None:
    #         return response

    #     # Don't set it if they used @xframe_options_exempt
    #     if getattr(response, 'xframe_options_exempt', False):
    #         return response

    #     response['X-Frame-Options'] = self.get_xframe_options_value(request,
    #                                                                 response)
    #     return response

    # def get_xframe_options_value(self, request, response):
    #     """
    #     Get the value to set for the X_FRAME_OPTIONS header. Use the value from
    #     the X_FRAME_OPTIONS setting, or 'SAMEORIGIN' if not set.

    #     This method can be overridden if needed, allowing it to vary based on
    #     the request or response.
    #     """
    #     return getattr(settings, 'X_FRAME_OPTIONS', 'SAMEORIGIN').upper()





