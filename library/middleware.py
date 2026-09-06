from django.core.cache import cache
from django.http import JsonResponse

class PrivacyMiddleware:
    def __init__(self,get_response): self.get_response=get_response
    LIMITS = {'/login/':10,'/api/propose/':20,'/api/finalize/':30,'/api/grammar/':20,'/api/mod22/':20,'/api/import/pdf/':12}

    def __call__(self,request):
        if request.method == 'POST' and request.path in self.LIMITS:
            identity = str(request.user.pk) if request.user.is_authenticated else request.META.get('REMOTE_ADDR','unknown')
            key = 'limit:'+request.path+identity
            cache.add(key,0,60)
            if cache.incr(key) > self.LIMITS[request.path]:
                return JsonResponse({'error':'Rate limit reached. Try again in one minute.'},status=429)
        response=self.get_response(request)
        response['Cache-Control']='no-store, private'
        response['X-Frame-Options']='DENY'
        response['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response
