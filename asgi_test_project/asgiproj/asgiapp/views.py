import asyncio

from django.views.generic import TemplateView


class TestView(TemplateView):

    template_name = 'index.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['context_test'] = 'Hello context test.'
        return context

    async def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        print("Testing asyncio")
        await asyncio.sleep(1)
        print("Async sleep end...")
        return self.render_to_response(context)
