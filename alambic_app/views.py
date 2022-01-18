import logging

from django.shortcuts import render
from django.http import JsonResponse, HttpResponseRedirect, HttpResponse
from formtools.wizard.views import SessionWizardView

from alambic_app.utils.data_management import *
from alambic_app.utils.exceptions import BadRequestError
from alambic_app import tasks

from celery.result import AsyncResult

# Create your views here.

logger = logging.getLogger(__name__)


def about(request):
    return render(request, 'about.html')


def documentation(request):
    return render(request, 'documentation.html')


def index(request):
    return render(request, 'home.html')


def upload(request):
    if request.method == 'POST':
        form = GeneralInfoInputForm(request.POST, request.FILES)
        if form.is_valid():
            result = tasks.upload_form_data.delay(filename=form.cleaned_data['input_file'],
                                                  model=form.cleaned_data['model'],
                                                  task=form.cleaned_data['task'])
            return HttpResponseRedirect("/pouring?id=" + result.id)
    else:
        form = GeneralInfoInputForm()
    return render(request, 'upload_data.html', {'form': form})


def pouring(request):
    if request.method == 'GET':
        params = request.GET
        if "id" not in params:
            raise BadRequestError("Missing job id")
        task_id = params["id"]
        return render(request, "pouring.html", {"token": task_id})
    raise BadRequestError("Invalid server request")


def job_status(request):
    """
    Shamelessly found in ORVAL code, by Alexandre Renaud
    Keep track of progress of pipelines
    """
    if request.method == 'GET':
        params = request.GET
        if "token" not in params:
            raise ValidationError("Invalid or missing job id.")
        job_id = params["token"]
        result = AsyncResult(job_id)
        if result.status == "SUCCESS":
            return JsonResponse({"token": job_id, "status": result.status})
        else:
            task_refs = tasks.get_pipeline_task_refs(job_id)
            success_counter = 0
            for task, task_ref in sorted(task_refs.items(), key=lambda kv: kv[1]["step"]):
                task_id = task_refs[task]["id"]
                result = tasks.get_task_signature(task).AsyncResult(task_id)
                if result.status == "FAILURE":
                    return JsonResponse({"id": job_id, "status": result.status})
                elif result.status == "SUCCESS":
                    success_counter += 1
            progress_status = "RUNNING..."  # ({0:.0f}%)".format(float(success_counter * 100)/len(task_refs))
            return JsonResponse(
                {"id": job_id,
                 "status": progress_status,
                 "current_step": success_counter + 1,
                 "total_steps": len(task_refs)}
            )
    raise BadRequestError("Invalid server request")


def chopping_ingredients(request):
    """
    Renders template page for the feature extraction and preprocessing
    Inspired by : https://stackoverflow.com/questions/17649976/celery-chain-monitoring-the-easy-way
    """
    if request.method == 'GET':
        params = request.GET
        if "id" not in params:
            raise BadRequestError("Missing job id")
        task_id = params["id"]
        return render(request, 'chopping.html', {'token': task_id})
    raise BadRequestError("Invalid server request")


def distilling(request):
    if request.method == 'GET':
        # TODO launch the machine learning algorithm + evaluation + query afterwards
        return render(request, 'distilling.html')
    raise BadRequestError("Invalid server request")


def tasting(request):
    if request.method == 'GET':
        annotation_template = get_annotation_template_page()
        # TODO check stop criterion and redirect to page final where the user can download the results and model
        # if stop_criterion:
        ## return HttpResponseRedirect("/spirit?id=" + result.id)
        return render(request, annotation_template)
    raise BadRequestError("Invalid server request")


def success(request):
    """
    Renders the page when the stop criterion has been reached, where you can
    download the model and the results (csv + plots)
    """
    if request.method == 'GET':
        params = request.GET
        if "id" not in params:
            raise BadRequestError("Missing result id")
        result_id = params["id"]
        return render(request, 'spirit.html', {'token': result_id})
    raise BadRequestError("Invalid server request")


class SetupView(SessionWizardView):
    template_name = "setup.html"
    form_list = get_default_form_list()

    # print(form_list)

    def get_context_data(self, form, **kwargs):
        context = super(SetupView, self).get_context_data(
            form=form, **kwargs)
        context.update({
            'data': cache.get('data', 0),
            'step_icons': {
                'Data': 'description',
                'Task': 'display_settings',
                'Model Settings': 'build',
                'Active Learning': 'co_present'
            }
        })

        return context

    def get_form(self, step=None, data=None, files=None):
        form = None

        if step is None:
            step = self.steps.current

        if step == "Data" and cache.get('data', 0) > 0:
            form_class = get_form_data()
            form = form_class(data)

        elif step == "Task":
            form_class = get_form_task()
            form = form_class(data)

        elif step == "Model Settings":
            model_choice = self.get_cleaned_data_for_step("Task")['model_choice']
            form_class = get_form_model(model_choice)
            form = form_class(data)

        elif step == "Active Learning":
            form_class = get_form_AL()
            form = form_class(data)

        else:
            BadRequestError("Invalid server request")

        return form

    def process_step(self, form):
        step_data = super().process_step(form)

        if self.steps.current == 'Data':
            pass

        return step_data

    def done(self, form_list, **kwargs):
        data_list = [form.cleaned_data for form in form_list]
        ## do something with it
        form_data = {
            'data': data_list[0],
            'task': data_list[1],
            'active': data_list[2]
        }
        result = tasks.preprocess_and_feature_extraction(form_data)
        return HttpResponseRedirect("/chopping?id=" + result.id)
