
from rest_framework.views import exception_handler


def custom_exception_handler(exc, context):
    response= exception_handler(exc, context)
    if response is not None:
        custom_response = {
            'success': False,
            'status_code': response.status_code,
            'error': response.data.get('detail', response.data),
            'message': 'An error occurred during the request.'
        }

        if response.status_code == 400:
            custom_response['message'] = 'Bad Request. Please check your payload.'
        elif response.status_code == 401:
            custom_response['message'] = 'Unauthorized. Your token is missing or expired.'
        elif response.status_code == 403:
            custom_response['message'] = 'Forbidden. You lack the required role permissions.'
        elif response.status_code == 404:
            custom_response['message'] = 'Not Found. The requested resource does not exist.'

        response.data = custom_response

    return response
