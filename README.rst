Experimenting with ASGI in Django's core. Just hacking away in the hope that I end up with something that may be helpful towards migrating Django to async. Starting out with the Channels handlers as a basis, pulling out the async_to_sync bits, and going from there.

Current branch: `async-experiment-2`

The test project in in `asgi_test_project` and is runnable using an ASGI server. Only tested simple GET responses with TemplateView so far. You can run the test app using `<hypercorn/uvicorn/daphne> asgiproj.asgi:application`. 
