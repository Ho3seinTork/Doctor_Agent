import os
import json
from dotenv import load_dotenv
import requests
import time
from typing import Tuple
import backoff
import urllib3

# Load environment variables securely to decouple configuration from code.
# This aids in maintaining environment-specific settings and supports the twelve-factor app methodology.
load_dotenv()
MISTRAL_API_KEY = os.getenv('MISTRAL_API_KEY')
MISTRAL_API_BASE = os.getenv('MISTRAL_API_BASE', 'https://api.mistral.ai')
MISTRAL_API_VERSION = "v1"
MISTRAL_API_ENDPOINT = f"{MISTRAL_API_BASE}/{MISTRAL_API_VERSION}/chat/completions"

# Configure optional proxies if defined, ensuring flexible network routing and compliance with corporate security policies.
HTTP_PROXY = os.getenv('HTTP_PROXY')
HTTPS_PROXY = os.getenv('HTTPS_PROXY')

# Initialize a persistence-enabled session object to facilitate connection reuse and integrated retry policies.
# This aligns with efficient resource management and minimizes overhead in network calls.
session = requests.Session()
if HTTP_PROXY or HTTPS_PROXY:
    session.proxies = {
        'http': HTTP_PROXY,
        'https': HTTPS_PROXY
    }

# Define a retry strategy using urllib3 to handle transient HTTP errors robustly.
# This strategy ensures graceful degradation under load and mitigates issues from intermittent connectivity.
retry_strategy = urllib3.util.Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504]
)
adapter = requests.adapters.HTTPAdapter(max_retries=retry_strategy)
session.mount("http://", adapter)
session.mount("https://", adapter)

# Establish a detailed system prompt to direct the AI's clinical responses.
# This design encourages consistency in diagnostic recommendations by aligning the model with domain-specific best practices.
SYSTEM_PROMPT = """شما یک پزشک متخصص هستید که باید با توجه به علائم بیمار، تشخیص احتمالی و توصیه‌های لازم را ارائه دهید.
لطفا پاسخ خود را در قالب زیر ارائه دهید:

📋 تشخیص احتمالی:
[تشخیص های احتمالی را به ترتیب اولویت ذکر کنید]
+ 5 تشخیص  بیماری احتمالی حاصل از علائم بالا

⚕️ توضیحات:
[توضیح مختصر در مورد دلیل این تشخیص ها]
+ پیشنهاد دارو های مناسب برای درمان

💊 توصیه‌ها:
[توصیه‌های لازم و اقدامات احتیاطی]
+ پیشنهاد مربوط به تغذیه  و سلامتی
+ پیشنهاد برای طب سنتی

⚠️ هشدارها:
[در صورت وجود علائم خطرناک یا نیاز به مراجعه فوری به پزشک]"""

# Apply the exponential backoff design pattern to manage transient failures.
# This decorator ensures that retry attempts are spaced exponentially, reducing the risk of overwhelming the API service.
@backoff.on_exception(
    backoff.expo,
    (requests.exceptions.RequestException, json.JSONDecodeError),
    max_tries=5,
    max_time=120
)
def make_api_request(headers: dict, data: dict, timeout: int = 90):
    """Perform an API call with integrated error handling and retry logic.
    
    This abstraction facilitates robust external integrations by capturing common I/O exceptions and providing
    insightful error messages that simplify downstream troubleshooting.
    """
    try:
        response = session.post(
            MISTRAL_API_ENDPOINT,
            headers=headers,
            json=data,
            timeout=(15, timeout)
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        # Indicates potential network latency or server-side slowness. Consider reviewing infrastructure if frequent.
        raise Exception("درخواست با تاخیر مواجه شد - لطفاً مجدداً تلاش کنید")
    except requests.exceptions.ConnectionError:
        # Highlights possible connectivity issues; ensure network availability or proxy configurations.
        raise Exception("خطای اتصال - لطفاً اتصال اینترنت خود را بررسی کنید")
    except requests.exceptions.HTTPError as e:
        # Handle specific HTTP errors to offer precise feedback and control application flow.
        if response.status_code == 401:
            raise Exception("کلید API نامعتبر است") from e
        elif response.status_code == 429:
            raise Exception("محدودیت تعداد درخواست. لطفاً چند دقیقه صبر کنید") from e
        elif response.status_code >= 500:
            raise Exception("خطای سرور Mistral AI") from e
        raise
    except Exception as e:
        # Fallback for all unexpected exceptions; log details may be required for post-mortem debugging.
        raise Exception(f"خطای غیرمنتظره: {str(e)}")

def call_language_model(prompt: str, max_retries: int = 3, retry_delay: int = 2) -> str:
    """Engage the Mistral AI API with meticulous error management and retry schemes.
    
    This function encapsulates the full interaction lifecycle with the external API, including fallback logic that
    maintains service continuity when facing repeated transient failures.
    """
    
    if not MISTRAL_API_KEY:
        return "خطا: کلید API یافت نشد"

    headers = {
        "Authorization": f"Bearer {MISTRAL_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    data = {
        "model": "mistral-medium",  # Align with defined model archetypes for consistent AI performance.
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7,
        "max_tokens": 2000,
        "stream": False
    }

    # Predefine a fallback response to ensure system responsiveness even when the external service fails repeatedly.
    fallback_response = """
📋 تشخیص احتمالی:
به دلیل اختلال در ارتباط با سرور، امکان تشخیص دقیق وجود ندارد.

⚕️ توضیحات:
لطفاً چند دقیقه دیگر مجدداً تلاش کنید.

💊 توصیه‌ها:
در صورت شدید بودن علائم، به پزشک مراجعه کنید.

⚠️ هشدارها:
این پاسخ موقت است و جایگزین مشاوره پزشکی نیست.
"""

    for attempt in range(max_retries):
        try:
            print(f"Making API request attempt {attempt + 1}")  # Log attempt to support traceability.
            response_data = make_api_request(headers, data)
            
            if 'choices' in response_data:
                content = response_data['choices'][0]['message']['content'].strip()
                if content:
                    return content
                
            print(f"Invalid response format on attempt {attempt + 1}")  # Alert on schema mismatch and potential API changes.
            if attempt < max_retries - 1:
                time.sleep(retry_delay * (attempt + 1))  # Exponential delay integration enhances overall system stability.
                continue
                
        except Exception as e:
            print(f"Error on attempt {attempt + 1}: {str(e)}")  # Error logging for operational diagnostics.
            if attempt < max_retries - 1:
                time.sleep(retry_delay * (attempt + 1))
                continue
            elif "Invalid API key" in str(e):
                return "خطا: کلید API نامعتبر است"
            elif "Rate limit exceeded" in str(e):
                return "خطا: محدودیت تعداد درخواست. لطفاً چند دقیقه صبر کنید"
            elif "server error" in str(e):
                return "خطا: سرور Mistral AI در دسترس نیست"
            
    # Return the predefined fallback response after all retry attempts have been exhausted.
    return fallback_response
