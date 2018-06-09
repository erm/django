from django.views.generic import View, TemplateView


# class TestView(View):

#     def get(self, request, *args, **kwargs):
#         return None


class TestView(TemplateView):

    template_name = 'index.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['context_test'] = 'Hello context test.'
        return context
