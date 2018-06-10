import asyncio
import asyncpg


from django.views.generic import TemplateView
from asgiapp.models import AsyncTest


# async def run():
#     conn = await asyncpg.connect(user='user', password='password',
#                                  database='database', host='127.0.0.1')
#     values = await conn.fetch('''SELECT * FROM mytable''')
#     await conn.close()


class TestView(TemplateView):

    template_name = 'index.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['context_test'] = 'Hello context test.'
        return context

    async def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        print("Testing asyncio")
        await asyncio.sleep(0.5)
        print("Async sleep end...")

        return self.render_to_response(context)

    async def post(self, request, *args, **kwargs):
        print(request.POST)
        return await self.get(request, *args, **kwargs)
