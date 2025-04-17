import os
import json
import asyncio 
from datetime import datetime
import uuid
import base64
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup, Update  # Add this import
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ApplicationBuilder,
    Application,
    CallbackQueryHandler 
)
from LLMs import call_language_model  
from dotenv import load_dotenv
import sys
import codecs

# Set console encoding for Windows
if sys.platform.startswith('win'):
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer)

# ----------------- Configuration -----------------
# Load environment variables
load_dotenv(r"C:\Users\Administrator\Desktop\Dr_Agent - With MistralAI\.env")
BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
BOT_USERNAME = os.getenv('TELEGRAM_BOT_USERNAME', '').lstrip('@')  # Remove @ if present
if not BOT_USERNAME:
    print("Warning: TELEGRAM_BOT_USERNAME not set in environment variables")
DB_FOLDER = r"C:\Users\Administrator\Desktop\Dr_Agent - With MistralAI\database"
DB_FILE = "patients.json"

# System prompt for your fine-tuned Mistral AI model
SYSTEM_PROMPT = """
You are an AI medical assistant. Analyze patient symptoms & context (age, gender, pregnancy, hypertension, diabetes, allergies) using the following steps:
Symptom Triaging:
Identify symptom patterns, duration, and red flags (e.g., chest pain, confusion, high fever).
Categorize disease state: acute/chronic/infectious.
Differential Diagnosis:

List 3–5 likely conditions (prioritize prevalence & risk factors).
Example: “سردرد + تاری دید + فشار خون بالا → پره اکلامپسی احتمالی در بارداری.”
Urgency Assessment:

Low: Mild/moderate, no red flags.
Medium: Progressive/worsening symptoms.
High: Presence of red flags (e.g., shortness of breath, loss of consciousness).
Include escalation triggers (e.g., “اگر تب به ۳۹°C رسید، فوریت به سطح بالا افزایش می‌یابد”).
Context-Safe Recommendations:

داروها:
بارداری: Avoid NSAIDs/تراتوژن‌ها; suggest acetaminophen (if liver is fine).
فشار خون: Avoid decongestants/corticosteroids.
جنسیت: For male UTIs use Trimethoprim; for females, Nitrofurantoin.
غیردارویی: Hydration, rest, cold compress.
Contraindications: Aspirin in children <12; metformin in renal failure.
Immediate Actions:

ER referral for high urgency plus safety-net advice (e.g., “اگر درد قفسه سینه دارید، فعالیت را متوقف کرده و با ۱۱۵ تماس بگیرید”).
Response Template (Persian):
۱. تشخیص‌های احتمالی:
[شرح شرایط + مثال: میگرن، عفونت ادراری]
۲. سطح فوریت:
[کم/متوسط/بالا] + [توضیح مختصر، مثال: "وجود تب بالا و سردرد شدید"]
۳. توصیه‌های ایمن:
[داروها/غیردارویی، مثال: "در بارداری: پاراستامول ۵۰۰mg هر ۸ ساعت (حداکثر ۳ روز)"]
[ممنوعیت‌ها: مثال: "اجتناب از ایبوپروفن در فشار خون کنترل نشده"]
۴. اقدامات اضطراری:
[مثال: "در صورت تنگی نفس ناگهانی، بلافاصله به اورژانس مراجعه کنید"]
⚠️ هشدار: این تحلیل جایگزین تشخیص پزشکی نیست. برای ارزیابی دقیق به پزشک یا بیمارستان مراجعه نمایید.

Instruction:
Respond in Persian using a professional, clear, and concise tone.
Always remind that the information is for informational purposes only and to consult a healthcare professional for diagnosis and treatment.
"""

# Load questions from JSON file
def load_questions():
    questions_file = r"C:\Users\Administrator\Desktop\Dr_Agent - With MistralAI\questions.json"
    try:
        with open(questions_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get('questions', [])  # Return the 'questions' array from the JSON
    except FileNotFoundError:
        print(f"Error: questions.json file not found at {questions_file}")
        return []
    except json.JSONDecodeError:
        print("Error: Invalid JSON format in questions.json")
        return []

# Initialize questions from JSON file        
QUESTIONS = load_questions()

# ----------------- States -----------------
# Add new state for section questions
GETTING_STARTED, GET_BASIC_INFO, GET_NAME, GET_AGE, GET_GENDER, GET_SECTION_ANSWERS, GET_ANSWERS, GET_EXTRA_INFO, CONFIRM_EXTRA_INFO, ASK_FOR_MEDICAL_HISTORY, GET_MEDICAL_HISTORY, DIAGNOSE = range(12)

# Add new states after existing states
VIEW_PROFILE, VIEW_HISTORY, SELECT_VISIT_VERSION = range(12, 15)

# Add path for patient info database
PATIENT_INFO_DB = "patient_info.json"

# Add medical history categories
MEDICAL_HISTORY_CATEGORIES = {
    'medical_history': [
        'بیماری‌های زمینه‌ای (مانند دیابت، فشار خون، بیماری‌های قلبی، آسم، اختلالات خودایمنی):',
        'جراحی‌های قبلی:',
        'داروهای مصرفی فعلی (با ذکر دوز و مدت مصرف):',
        'آلرژی‌ها (دارویی، غذایی، محیطی):',
        'سابقه بستری شدن:'
    ],
    'current_symptoms': [
        'شرح حال اصلی (دلیل اصلی مراجعه):',
        'زمان شروع علائم:',
        'مدت زمان علائم (ساعتی، روزانه، هفتگی):',
        'شدت علائم (مقیاس ۱ تا ۱۰):',
        'عوامل تشدیدکننده/تسکین‌دهنده:',
        'الگوی زمانی (مثلاً شبانه‌روزی، فصلی):',
        'علائم همراه (تب، لرز، تعریق، کاهش وزن ناخواسته، خستگی، سرگیجه و...):'
    ],
    'physical_exam': [
        'فشار خون:',
        'دمای بدن:',
        'نبض:',
        'تنفس:',
        'یافته‌های قابل توجه (رنگ پوست، تورم، زخم، راش):',
        'معاینه سیستم‌ها (قلبی-عروقی، تنفسی، گوارشی، عصبی):'
    ],
    'lifestyle': [
        'سیگار/قلیان (مقدار و مدت مصرف):',
        'مصرف الکل یا مواد مخدر:',
        'رژیم غذایی (گیاهخواری، پرچرب، کم‌پروتئین و...):',
        'فعالیت بدنی (کم‌تحرک، ورزش منظم):',
        'شغل و محیط کار (مواجهه با مواد شیمیایی، استرس، آلودگی):'
    ],
    'family_history': [
        'بیماری‌های ارثی/خانوادگی (دیابت، سرطان، بیماری‌های قلبی، اختلالات روانی):'
    ],
    'female_specific': [
        'وضعیت قاعدگی:',
        'آخرین قاعدگی:',
        'نظم سیکل:',
        'بارداری (هفته):',
        'شیردهی:',
        'روش‌های پیشگیری از بارداری:'
    ],
    'other_info': [
        'سابقه مسافرت اخیر (برای بررسی بیماری‌های عفونی):',
        'تماس با بیماران عفونی:',
        'واکسیناسیون‌ها (مثلاً کووید-۱۹، کزاز):'
    ]
}

async def start(update, context):
    """Handle /start command and deep links"""
    # Check if this is a deep link with visit parameter
    args = context.args
    if args and args[0].startswith('visit_'):
        return await process_visit_link(update, context, args[0])
        
    # Regular start command handling
    user = update.message.from_user
    user_id = user.id
    welcome_msg = (
        f"سلام {user.first_name}! 👋\n\n"
        "به سیستم هوشمند تشخیص بیماری خوش آمدید.\n"
        "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:\n\n"
        "در صورت دیدن آموزش کار با ربات و با خبر بودن از اخبار دستیار پزشک - Doctor Agent در کانال تلگرامی زیر عضو شوید:\n"
        "🆔 @DrAgent_channel"
    )
    
    main_menu = [
        ["👤 مشاهده پروفایل و اطلاعات"],
        ["📋 تاریخچه ویزیت‌ها"],
        ['🏥 شروع تشخیص و ویزیت جدید']
    ]
    
    await update.message.reply_text(
        welcome_msg,
        reply_markup=ReplyKeyboardMarkup(main_menu, resize_keyboard=True)
    )
    return GETTING_STARTED

async def process_visit_link(update, context, visit_param):
    """Process visit deep link parameter"""
    try:
        # Extract and decode visit identifier
        encoded_data = visit_param.replace('visit_', '')
        padded_data = encoded_data + '=' * (-len(encoded_data) % 4)
        decoded_data = base64.urlsafe_b64decode(padded_data).decode()
        user_id, timestamp = decoded_data.split('-', 1)
        
        # Load visit from database
        visit = await load_visit_by_id_and_timestamp(int(user_id), timestamp)
        
        if not visit:
            raise ValueError("Visit record not found")
        
        # Store visit in context
        context.user_data['selected_visit'] = visit
        
        # Format and send visit details
        await send_visit_details(update, visit)
        
        # Show action buttons
        action_buttons = [
            ['📋 مشاهده جزئیات تشخیص'],
            ['💊 مشاهده توصیه‌های درمانی'],
            ['🔙 بازگشت به منوی اصلی']
        ]
        
        await update.message.reply_text(
            "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:",
            reply_markup=ReplyKeyboardMarkup(action_buttons, resize_keyboard=True)
        )
        return SELECT_VISIT_VERSION
        
    except Exception as e:
        print(f"Error processing visit link: {e}")
        await update.message.reply_text(
            "❌ خطا در بازیابی اطلاعات ویزیت.\n"
            "لطفاً از صحت لینک اطمینان حاصل کنید.",
            reply_markup=ReplyKeyboardMarkup([['🔙 بازگشت به منوی اصلی']], resize_keyboard=True)
        )
        return GETTING_STARTED

async def load_visit_by_id_and_timestamp(user_id, timestamp):
    """Load specific visit from database"""
    if os.path.exists(os.path.join(DB_FOLDER, DB_FILE)):
        try:
            with open(os.path.join(DB_FOLDER, DB_FILE), 'r', encoding='utf-8') as f:
                visits = json.load(f)
                return next(
                    (v for v in visits 
                     if v.get('user_id') == user_id and 
                     v.get('visit_timestamp', '').startswith(timestamp)),
                    None
                )
        except Exception as e:
            print(f"Error loading visit data: {e}")
    return None

async def check_existing_info(user_id):
    if os.path.exists(PATIENT_INFO_DB):
        with open(PATIENT_INFO_DB, 'r', encoding='utf-8') as f:
            patient_records = json.load(f)
            for record in patient_records:
                if record['user_id'] == user_id:
                    return record
    return None

async def handle_start_choice(update, context):
    choice = update.message.text.strip()  # Add strip() to remove any whitespace
    user_id = update.message.from_user.id

    # Update the button text matching to be exact
    if choice == "👤 مشاهده پروفایل و اطلاعات":
        await show_profile(update, context)
        return GETTING_STARTED
    elif choice == "📋 تاریخچه ویزیت‌ها":
        return await show_visit_history(update, context)
    elif choice == '🏥 شروع تشخیص و ویزیت جدید':
        existing_info = await check_existing_info(user_id)
        
        if existing_info:
            context.user_data['patient_info'] = existing_info
            # Initialize section answers
            context.user_data['answers'] = {}
            context.user_data['current_section'] = 0
            context.user_data['sections'] = get_sections()
            context.user_data['all_questions'] = parse_questions()
            
            section = context.user_data['sections'][0]
            section_name = section['name']
            
            explanation = (
                "⚕️ راهنمای پاسخ‌دهی:\n"
                "✅ = .بله، علائمی در این بخش دارم\n"
                "❌ = .خیر، علائمی در این بخش ندارم\n\n"
                "لطفا متن هر پیام را با دقت فراوان خوانده و سپس بر روی گزینه کلیک کنید، چون بازگشت ندارد.\n\n"
                "لطفاً مشخص کنید در کدام بخش‌های بدن علائم دارید:\n\n"
            )
            await update.message.reply_text(explanation)
            await update.message.reply_text(
                f"بخش: {section_name}\n\n"
                "آیا در این بخش علائمی دارید؟",
                reply_markup=ReplyKeyboardMarkup([['✅', '❌']], resize_keyboard=True)
            )
            return GET_SECTION_ANSWERS
        else:
            return await request_patient_name(update, context)
    
    # Update the button texts in error message to match exactly
    main_menu = [
        ["👤 مشاهده پروفایل و اطلاعات"],
        ["📋 تاریخچه ویزیت‌ها"],
        ['🏥 شروع تشخیص و ویزیت جدید']
    ]
    
    await update.message.reply_text(
        "لطفاً یکی از گزینه‌های موجود را انتخاب کنید.",
        reply_markup=ReplyKeyboardMarkup(main_menu, resize_keyboard=True)
    )
    return GETTING_STARTED

async def show_profile(update, context):
    user_id = update.message.from_user.id
    
    # Load patient info from database
    if os.path.exists(PATIENT_INFO_DB):
        with open(PATIENT_INFO_DB, 'r', encoding='utf-8') as f:
            patient_records = json.load(f)
            patient_info = next((record for record in patient_records 
                               if record['user_id'] == user_id), None)
    
    # Load visit history
    visits = []
    if os.path.exists(os.path.join(DB_FOLDER, DB_FILE)):
        with open(os.path.join(DB_FOLDER, DB_FILE), 'r', encoding='utf-8') as f:
            all_visits = json.load(f)
            visits = [v for v in all_visits if v['user_id'] == user_id]

    if patient_info:
        profile_text = (
            "👤 اطلاعات پروفایل:\n\n"
            f"نام و نام خانوادگی: {patient_info.get('name', 'ثبت نشده')}\n"
            f"سن: {patient_info.get('age', 'ثبت نشده')}\n"
            f"جنسیت: {patient_info.get('gender', 'ثبت نشده')}\n\n"
            f"📊 تعداد ویزیت‌ها: {len(visits)}\n\n"
            "آخرین ویزیت‌ها:"
        )
        
        # Add last 3 visits with error handling
        for i, visit in enumerate(visits[-3:], 1):
            try:
                visit_date = datetime.fromisoformat(visit.get('visit_timestamp', '')).strftime("%Y-%m-%d %H:%M")
            except (ValueError, TypeError):
                visit_date = "تاریخ نامشخص"
            profile_text += f"\n{i}. {visit_date}"
    else:
        profile_text = "❌ اطلاعات پروفایل ثبت نشده است."

    # Update main menu button texts to match exactly
    main_menu = [
        ["👤 مشاهده پروفایل و اطلاعات"],
        ["📋 تاریخچه ویزیت‌ها"],
        ['🏥 شروع تشخیص و ویزیت جدید']
    ]
    
    await update.message.reply_text(
        profile_text,
        reply_markup=ReplyKeyboardMarkup(main_menu, resize_keyboard=True)
    )
    return GETTING_STARTED

def generate_visit_code(user_id, timestamp):
    """Generate a unique visit code based on user ID and timestamp."""
    # Create a unique string combining user_id and timestamp
    unique_str = f"{user_id}-{timestamp.strftime('%Y%m%d-%H%M%S')}"
    # Create a URL-safe Base64 encoded string
    encoded = base64.urlsafe_b64encode(unique_str.encode()).decode()
    # Return a shorter, clean code
    return f"VISIT-{encoded[:12]}"

def generate_visit_link(user_id, timestamp):
    """Generate a deep link for the Telegram bot."""
    # Create a unique identifier combining user_id and timestamp
    visit_id = f"{user_id}-{timestamp.strftime('%Y%m%d-%H%M%S')}"
    # Base64 encode for URL safety
    encoded_id = base64.urlsafe_b64encode(visit_id.encode()).decode().rstrip('=')
    # Generate bot deep link with visit_ prefix
    if BOT_USERNAME:
        return f"https://t.me/{BOT_USERNAME}?start=visit_{encoded_id}"
    return None

async def handle_deep_link(update, context):
    """Handle visit deep links."""
    try:
        args = context.args
        if not args or not args[0].startswith('visit_'):
            return await start(update, context)

        # Extract and decode visit identifier
        encoded_data = args[0].replace('visit_', '')
        # Add padding if needed
        padded_data = encoded_data + '=' * (-len(encoded_data) % 4)
        # Decode the visit identifier
        decoded_data = base64.urlsafe_b64decode(padded_data).decode()
        user_id, timestamp = decoded_data.split('-', 1)

        # Load visit from database
        visit = None
        if os.path.exists(os.path.join(DB_FOLDER, DB_FILE)):
            with open(os.path.join(DB_FOLDER, DB_FILE), 'r', encoding='utf-8') as f:
                visits = json.load(f)
                for v in visits:
                    if (str(v.get('user_id')) == user_id and 
                        v.get('visit_timestamp', '').startswith(timestamp)):
                        visit = v
                        break

        if not visit:
            raise ValueError("Visit record not found")

        # Store visit in context
        context.user_data['selected_visit'] = visit

        # Format visit info for display
        visit_date = datetime.fromisoformat(visit['visit_timestamp']).strftime("%Y-%m-%d %H:%M")
        
        info_text = (
            f"📋 اطلاعات ویزیت پزشکی\n"
            f"🔖 کد ویزیت: {visit.get('visit_code', 'نامشخص')}\n"
            f"📅 تاریخ مراجعه: {visit_date}\n\n"
            f"👤 بیمار: {visit.get('name', 'نامشخص')}\n"
            f"📅 سن: {visit.get('age', 'نامشخص')}\n"
            f"⚧ جنسیت: {visit.get('gender', 'نامشخص')}\n\n"
        )

        if visit.get('medical_history'):
            info_text += "📚 سوابق پزشکی ثبت شده است\n"
        if visit.get('answers'):
            info_text += "🔍 علائم اصلی ثبت شده است\n"

        keyboard = [
            ['📋 مشاهده جزئیات تشخیص'],
            ['💊 مشاهده توصیه‌های درمانی'],
            ['🔙 بازگشت به منوی اصلی']
        ]

        await update.message.reply_text(
            info_text,
            reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        )
        return SELECT_VISIT_VERSION

    except Exception as e:
        print(f"Deep link error: {e}")
        await update.message.reply_text(
            "❌ خطا در دسترسی به اطلاعات ویزیت.\n"
            "لطفاً از صحت لینک اطمینان حاصل کنید.",
            reply_markup=ReplyKeyboardMarkup([['🔙 بازگشت به منوی اصلی']], resize_keyboard=True)
        )
        return GETTING_STARTED

async def show_visit_history(update, context):
    user_id = update.message.from_user.id
    
    # Load visits from database
    visits = []
    db_path = os.path.join(DB_FOLDER, DB_FILE)
    if os.path.exists(db_path):
        try:
            with open(db_path, 'r', encoding='utf-8') as f:
                all_visits = json.load(f)
                # Filter visits for current user and ensure they have required fields
                visits = [v for v in all_visits if (
                    v.get('user_id') == user_id and 
                    isinstance(v.get('visit_timestamp'), str)
                )]
                
                # Sort visits by timestamp (most recent first)
                visits.sort(key=lambda x: x.get('visit_timestamp', ''), reverse=True)
        except json.JSONDecodeError:
            print("Error reading visits database")
    
    if not visits:
        await update.message.reply_text(
            "تاریخچه ویزیتی یافت نشد.",
            reply_markup=ReplyKeyboardMarkup([
                ["👤 مشاهده پروفایل و اطلاعات"],
                ["🏥 شروع تشخیص و ویزیت جدید"]
            ], resize_keyboard=True)
        )
        return GETTING_STARTED
    
    # Store visits in context for later use
    context.user_data['visits'] = visits
    
    # Create buttons for each visit
    visit_buttons = []
    for visit in visits[:10]:  # Show last 10 visits
        try:
            visit_date = datetime.fromisoformat(visit['visit_timestamp']).strftime("%Y-%m-%d %H:%M")
            visit_code = visit.get('visit_code', generate_visit_code(user_id, datetime.fromisoformat(visit['visit_timestamp'])))
            visit_buttons.append([f"📋 {visit_date} | کد: {visit_code}"])
        except (ValueError, KeyError):
            continue
    
    visit_buttons.append(['🔙 بازگشت به منوی اصلی'])
    
    await update.message.reply_text(
        "📋 تاریخچه ویزیت‌های شما:\n"
        "لطفاً یک ویزیت را انتخاب کنید:",
        reply_markup=ReplyKeyboardMarkup(visit_buttons, resize_keyboard=True)
    )
    return VIEW_HISTORY

async def handle_visit_selection(update, context):
    choice = update.message.text
    
    if choice == '🔙 بازگشت به منوی اصلی':
        return await start(update, context)
    
    # Extract visit code from button text
    try:
        visit_code = choice.split('کد: ')[1]
    except IndexError:
        await update.message.reply_text("ویزیت نامعتبر است.")
        return VIEW_HISTORY
    
    visits = context.user_data.get('visits', [])
    selected_visit = None
    
    # Find the visit with matching code
    for visit in visits:
        if visit.get('visit_code') == visit_code:
            selected_visit = visit
            break
    
    if not selected_visit:
        await update.message.reply_text(
            "ویزیت مورد نظر یافت نشد.",
            reply_markup=ReplyKeyboardMarkup([['🔙 بازگشت به منوی اصلی']], resize_keyboard=True)
        )
        return VIEW_HISTORY
    
    # Store selected visit in context
    context.user_data['selected_visit'] = selected_visit
    
    # Show version options
    version_buttons = [
        ['نسخه تشخیص'],
        ['نسخه تجویز'],
        ['🔙 بازگشت به لیست ویزیت‌ها']
    ]
    
    await update.message.reply_text(
        "لطفاً نوع گزارش را انتخاب کنید:",
        reply_markup=ReplyKeyboardMarkup(version_buttons, resize_keyboard=True)
    )
    return SELECT_VISIT_VERSION

async def request_patient_name(update, context):
    await update.message.reply_text(
        "لطفاً نام و نام خانوادگی خود را وارد کنید:",
        reply_markup=ReplyKeyboardRemove()
    )
    return GET_NAME

async def save_name(update, context):
    if 'patient_info' not in context.user_data:
        context.user_data['patient_info'] = {}
    
    context.user_data['patient_info']['user_id'] = update.message.from_user.id
    context.user_data['patient_info']['name'] = update.message.text
    
    await update.message.reply_text("لطفاً سن خود را وارد کنید (عدد):")
    return GET_AGE

async def save_age(update, context):
    try:
        age = int(update.message.text)
        if 0 <= age <= 120:
            context.user_data['patient_info']['age'] = age
            gender_keyboard = ReplyKeyboardMarkup([['مرد', 'زن']], resize_keyboard=True)
            await update.message.reply_text(
                "لطفاً جنسیت خود را انتخاب کنید:",
                reply_markup=gender_keyboard
            )
            return GET_GENDER
        else:
            await update.message.reply_text("لطفاً سن معتبر وارد کنید (بین 0 تا 120):")
            return GET_AGE
    except ValueError:
        await update.message.reply_text("لطفاً فقط عدد وارد کنید:")
        return GET_AGE

async def save_gender_and_proceed(update, context):
    gender = update.message.text
    if gender not in ['مرد', 'زن']:
        await update.message.reply_text(
            "لطفاً جنسیت را از بین گزینه‌های موجود انتخاب کنید:",
            reply_markup=ReplyKeyboardMarkup([['مرد', 'زن']], resize_keyboard=True)
        )
        return GET_GENDER
    
    context.user_data['patient_info']['gender'] = gender
    
    # Save/Update patient info in database
    try:
        patient_records = []
        if os.path.exists(PATIENT_INFO_DB):
            try:
                with open(PATIENT_INFO_DB, 'r', encoding='utf-8') as f:
                    patient_records = json.load(f)
            except json.JSONDecodeError:
                # فایل خالی یا معتبر نیست، با لیست خالی شروع می‌کنیم
                patient_records = []
        
        # Update existing record or add new one
        updated = False
        for i, record in enumerate(patient_records):
            if record['user_id'] == context.user_data['patient_info']['user_id']:
                patient_records[i] = context.user_data['patient_info']
                updated = True
                break
        
        if not updated:
            patient_records.append(context.user_data['patient_info'])
        
        with open(PATIENT_INFO_DB, 'w', encoding='utf-8') as f:
            json.dump(patient_records, f, ensure_ascii=False, indent=2)
        
        info_summary = (
            "✅ اطلاعات پایه شما با موفقیت ثبت شد:\n\n"
            f"👤 نام و نام خانوادگی: {context.user_data['patient_info']['name']}\n"
            f"📅 سن: {context.user_data['patient_info']['age']}\n"
            f"⚧ جنسیت: {context.user_data['patient_info']['gender']}\n\n"
            "🏥 معاینه را شروع می‌کنیم..."
        )
        
        # ارسال خلاصه اطلاعات با دکمه شروع معاینه
        await update.message.reply_text(
            info_summary,
            reply_markup=ReplyKeyboardMarkup([['شروع معاینه']], resize_keyboard=True)
        )
        
        # Initialize section answers
        context.user_data['answers'] = {}
        context.user_data['current_section'] = 0
        context.user_data['sections'] = get_sections()
        context.user_data['all_questions'] = parse_questions()
        
        section = context.user_data['sections'][0]
        section_name = section['name']  # Use 'name' from section dictionary
        explanation = (
            "⚕️ راهنمای پاسخ‌دهی:\n"
            "✅ = بله، علائمی در این بخش دارم\n"
            "❌ = خیر، علائمی در این بخش ندارم\n\n"
            "لطفاً مشخص کنید در کدام بخش‌های بدن علائم دارید:\n\n"
        )
        await update.message.reply_text(explanation)
        await update.message.reply_text(
            f"بخش: {section_name}\n\n"
            "آیا در این بخش علائمی دارید؟",
            reply_markup=ReplyKeyboardMarkup([['✅', '❌']], resize_keyboard=True)
        )
        return GET_SECTION_ANSWERS
        
    except Exception as e:
        error_message = f"خطا در ذخیره اطلاعات: {str(e)}"
        print(error_message)  # ثبت خطا در لاگ
        await update.message.reply_text("متأسفانه مشکلی در ثبت اطلاعات پیش آمده. لطفاً دوباره تلاش کنید.")
        return ConversationHandler.END
        

# Add debug logging function
def log_debug(message):
    """Helper function for consistent debug logging"""
    print(f"[DEBUG] {message}")

# Update parse_questions function to better handle section structure
def parse_questions():
    """Parse questions from loaded JSON data"""
    questions = load_questions()
    parsed_questions = []
    
    for section in questions:
        section_title = section.get('title', '')
        for symptom in section.get('symptoms', []):
            parsed_questions.append({
                'section': section_title,
                'question': symptom.get('description', ''),
                'description': symptom.get('description', '')
            })
    
    return parsed_questions

# Update get_sections function with better error handling
def get_sections():
    """Get sections from loaded JSON data"""
    questions = load_questions()
    sections = []
    
    for section in questions:
        sections.append({
            'index': section.get('id', 0),
            'title': section.get('title', ''),
            'name': section.get('title', '')
        })
    
    return sections

async def handle_section_answers(update, context):
    """Handle responses for main section categories"""
    if 'sections' not in context.user_data:
        context.user_data.update({
            'answers': {},
            'current_section': 0,
            'sections': get_sections(),
            'all_questions': parse_questions(),
            'section_responses': {},
            'progress': {
                'total_sections': len(load_questions()),
                'current_section': 0,
                'answered_questions': 0
            }
        })

    answer = update.message.text
    current_section = context.user_data['sections'][context.user_data['current_section']]
    
    if answer not in ['✅', '❌']:
        await update.message.reply_text(
            "لطفاً از دکمه‌های ✅ یا ❌ استفاده کنید.",
            reply_markup=ReplyKeyboardMarkup([['✅', '❌']], resize_keyboard=True)
        )
        return GET_SECTION_ANSWERS

    # Store main section response
    context.user_data.setdefault('section_responses', {})
    context.user_data['section_responses'][current_section['title']] = answer

    if answer == '✅':
        # Find the matching section in QUESTIONS
        section_data = next(
            (section for section in QUESTIONS if section['title'] == current_section['title']),
            None
        )
        
        if section_data and section_data.get('symptoms'):
            # Store questions and initialize index
            context.user_data['current_section_questions'] = section_data['symptoms']
            context.user_data['current_question_index'] = 0
            
            # Ask first question
            return await ask_section_question(update, context)
    
    # Move to next section if no symptoms or all questions answered
    return await move_to_next_section(update, context)

async def ask_section_question(update, context):
    """Ask questions for sections with symptoms"""
    # Validate required data exists
    if not all(key in context.user_data for key in ['current_section_symptoms', 'current_question_index']):
        return await handle_sections_completion(update, context)
    
    current_symptoms = context.user_data['current_section_symptoms']
    current_index = context.user_data['current_question_index']
    
    # Check if we've completed all questions in current section
    if (current_index >= len(current_symptoms)):
        # Move to next section
        context.user_data['current_section'] += 1
        # Reset question index
        context.user_data['current_question_index'] = 0
        # Clear current section symptoms
        context.user_data.pop('current_section_symptoms', None)
        
        # Check if we've completed all sections
        if context.user_data['current_section'] >= len(context.user_data['sections']):
            return await handle_sections_completion(update, context)
        else:
            return await check_section(update, context)
            
    symptom = current_symptoms[current_index]
    current_section = context.user_data['sections'][context.user_data['current_section']]
    
    await update.message.reply_text(
        f"🔹 {current_section['title']}\n"
        f"سؤال {current_index + 1}/{len(current_symptoms)}:\n\n"
        f"🔍 {symptom.get('description', symptom)}",
        reply_markup=ReplyKeyboardMarkup([['✅', '❌']], resize_keyboard=True)
    )
    return GET_ANSWERS

async def move_to_next_section(update, context):
    """Progress to the next main section"""
    context.user_data['current_section'] += 1
    context.user_data['progress']['current_section'] += 1
    
    # Check if there are more sections
    if context.user_data['current_section'] < len(context.user_data['sections']):
        next_section = context.user_data['sections'][context.user_data['current_section']]
        
        # Show overall progress
        progress = context.user_data['progress']
        progress_msg = (
            f"پیشرفت کلی: {progress['current_section']}/{progress['total_sections']} بخش\n"
            f"علائم ثبت شده: {len(context.user_data.get('answers', {}))}\n\n"
            f"🔹 بخش بعدی: {next_section['name']}\n"
            "آیا در این بخش علائمی دارید؟"
        )
        
        await update.message.reply_text(
            progress_msg,
            reply_markup=ReplyKeyboardMarkup([['✅', '❌']], resize_keyboard=True)
        )
        return GET_SECTION_ANSWERS
    
    # All sections completed
    return await handle_sections_completion(update, context)

async def handle_answers(update, context):
    """Process answers for sub-questions within a section"""
    answer = update.message.text
    
    if answer not in ['✅', '❌']:
        await update.message.reply_text(
            "لطفاً از دکمه‌های ✅ یا ❌ استفاده کنید.",
            reply_markup=ReplyKeyboardMarkup([['✅', '❌']], resize_keyboard=True)
        )
        return GET_ANSWERS

    current_section = context.user_data['sections'][context.user_data['current_section']]
    current_q = context.user_data['current_section_questions'][context.user_data['current_question_index']]
    
    # Save answer if positive
    if answer == '✅':
        context.user_data.setdefault('answers', {})[current_q['description']] = {
            'section': current_section['title'],
            'answer': answer,
            'description': current_q['description']
        }
    
    # Move to next question
    context.user_data['current_question_index'] += 1
    context.user_data['progress']['answered_questions'] += 1
    
    # Continue with next question in current section
    return await ask_section_question(update, context)

async def handle_sections_completion(update, context):
    """Handle completion of all sections"""
    summary = "✅ تمام بخش‌ها بررسی شدند.\n\n"
    
    # Generate summary of positive answers
    if context.user_data.get('answers'):
        for section, answers in context.user_data['answers'].items():
            if isinstance(answers, list) and answers:  # Check if answers is a list and not empty
                summary += f"🔹 {section}:\n"
                for answer in answers:
                    if isinstance(answer, dict) and answer.get('answer') == '✅':
                        summary += f"  • {answer.get('description', '')}\n"
                summary += "\n"
    
    summary += "\nلطفاً هرگونه توضیحات اضافی یا علائم دیگری که فکر می‌کنید مهم است را بنویسید:"
    
    await update.message.reply_text(
        summary,
        reply_markup=ReplyKeyboardRemove()
    )
    
    # Ask if user wants to provide medical history after getting extra info
    await update.message.reply_text(
        "آیا مایل به تکمیل سوابق پزشکی هستید؟",
        reply_markup=ReplyKeyboardMarkup([['بله', 'خیر']], resize_keyboard=True)
    )
    
    return ASK_FOR_MEDICAL_HISTORY

async def save_data(update, context):
    # Store the extra info temporarily
    context.user_data['temp_extra_info'] = update.message.text
    
    confirmation_message = (
        "📝 اطلاعات وارد شده:\n\n"
        f"{context.user_data['temp_extra_info']}\n\n"
        "آیا این اطلاعات را تأیید می‌کنید؟"
    )
    
    confirm_keyboard = ReplyKeyboardMarkup([
        ['✅ تأیید اطلاعات'],
        ['✏️ ویرایش اطلاعات']
    ], resize_keyboard=True)
    
    await update.message.reply_text(confirmation_message, reply_markup=confirm_keyboard)
    return CONFIRM_EXTRA_INFO

async def handle_extra_info_confirmation(update, context):
    choice = update.message.text
    
    if choice == '✏️ ویرایش اطلاعات':
        await update.message.reply_text(
            "لطفاً مجدداً توضیحات اضافی یا علائم دیگر را وارد کنید:",
            reply_markup=ReplyKeyboardRemove()
        )
        return GET_EXTRA_INFO
    
    if choice == '✅ تأیید اطلاعات':
        # Save confirmed information
        if 'temp_extra_info' in context.user_data:
            context.user_data['extra_info'] = context.user_data['temp_extra_info']
            del context.user_data['temp_extra_info']
        else:
            context.user_data['extra_info'] = ''

        # Initialize section answers structure 
        context.user_data['answers'] = {}
        context.user_data['current_section'] = 0
        context.user_data['sections'] = get_sections()
        
        # Start with first section
        section = context.user_data['sections'][0]
        section_name = section['name']
        
        # Show instructions and first section question
        explanation = (
            "⚕️ راهنمای پاسخ‌دهی:\n"
            "✅ = بله، علائمی در این بخش دارم\n"
            "❌ = خیر، علائمی در این بخش ندارم\n\n"
            "لطفاً مشخص کنید در کدام بخش‌های بدن علائم دارید:\n\n"
        )
        
        await update.message.reply_text(explanation)
        await update.message.reply_text(
            f"بخش: {section_name}\n\n"
            "آیا در این بخش علائمی دارید؟",
            reply_markup=ReplyKeyboardMarkup([['✅', '❌']], resize_keyboard=True)
        )
        return GET_SECTION_ANSWERS
    
    # If neither confirmation nor edit was selected
    await update.message.reply_text(
        "لطفاً یکی از گزینه‌های موجود را انتخاب کنید.",
        reply_markup=ReplyKeyboardMarkup([
            ['✅ تأیید اطلاعات'],
            ['✏️ ویرایش اطلاعات']
        ], resize_keyboard=True)
    )
    return CONFIRM_EXTRA_INFO  # Return to confirm info state

# Add new handler for medical history collection 
async def handle_medical_history_choice(update, context):
    choice = update.message.text
    
    if choice == 'خیر':
        return await prepare_final_summary(update, context)
    
    if choice != 'بله':
        await update.message.reply_text(
            "لطفاً یکی از گزینه‌های بله یا خیر را انتخاب کنید.",
            reply_markup=ReplyKeyboardMarkup([['بله', 'خیر']], resize_keyboard=True)
        )
        return ASK_FOR_MEDICAL_HISTORY
    
    # Initialize medical history collection
    context.user_data['medical_history'] = {}
    context.user_data['current_category'] = list(MEDICAL_HISTORY_CATEGORIES.keys())[0]
    context.user_data['current_question_index'] = 0
    
    # Check if we should skip female-specific questions for male patients
    if context.user_data.get('patient_info', {}).get('gender') == 'مرد':
        context.user_data['skip_female_questions'] = True
    
    return await ask_next_medical_question(update, context)

# Update ask_next_medical_question to prompt supplementary info when a category's questions are all answered
async def ask_next_medical_question(update, context):
    current_category = context.user_data['current_category']
    current_index = context.user_data['current_question_index']
    questions = MEDICAL_HISTORY_CATEGORIES[current_category]
    category_names = {
        'medical_history': 'تاریخچه پزشکی',
        'current_symptoms': 'علائم فعلی',
        'physical_exam': 'معاینه فیزیکی',
        'lifestyle': 'سبک زندگی و محیطی',
        'family_history': 'سوابق خانوادگی',
        'female_specific': 'اطلاعات ویژه بانوان',
        'other_info': 'سایر اطلاعات'
    }

    if current_index >= len(questions):
        # Move to next category
        categories = list(MEDICAL_HISTORY_CATEGORIES.keys())
        current_cat_index = categories.index(current_category)
        
        # Find next appropriate category
        next_category = None
        for i in range(current_cat_index + 1, len(categories)):
            # Skip female-specific questions for male patients
            if (categories[i] == 'female_specific' and 
                context.user_data.get('skip_female_questions')):
                continue
            next_category = categories[i]
            break
            
        if next_category:
            context.user_data['current_category'] = next_category
            context.user_data['current_question_index'] = 0
            return await ask_next_medical_question(update, context)
        else:
            # All categories complete, move to final summary
            return await prepare_final_summary(update, context)
            
    question = questions[current_index]
    message_text = (
        f"📋 {category_names[current_category]}\n\n"
        f"🔍 {question}\n\n"
        "لطفا جمله را به صورت کامل و واضح بنویسید.\n"
        "مثال: دمای بدن من 36 است.\n"
        "مثال: داروی مصرفی من استامینافن است.\n"
        "مثال: آلرژی و حساسیت به انگور دارم.\n\n"
        "اگر اطلاعاتی ندارید، می‌توانید 'ندارم' یا '-' وارد کنید."
    )
    await update.message.reply_text(
        message_text,
        reply_markup=ReplyKeyboardRemove()
    )
    return GET_MEDICAL_HISTORY

async def save_medical_history_answer(update, context):
    answer = update.message.text
    current_category = context.user_data['current_category']
    current_index = context.user_data['current_question_index']
    
    # Initialize the category in medical_history if it doesn't exist
    if 'medical_history' not in context.user_data:
        context.user_data['medical_history'] = {}
    if current_category not in context.user_data['medical_history']:
        context.user_data['medical_history'][current_category] = {}
    
    # Save the answer
    context.user_data['medical_history'][current_category][current_index] = answer
    context.user_data['current_question_index'] += 1
    
    # Check if we've finished all questions in current category
    if current_index + 1 >= len(MEDICAL_HISTORY_CATEGORIES[current_category]):
        # Move to next category
        categories = list(MEDICAL_HISTORY_CATEGORIES.keys())
        current_cat_index = categories.index(current_category)
        
        # Skip female-specific questions for male patients
        next_category = None
        for i in range(current_cat_index + 1, len(categories)):
            if categories[i] == 'female_specific' and context.user_data.get('patient_info', {}).get('gender') == 'مرد':
                continue
            next_category = categories[i]
            break
            
        if next_category:
            context.user_data['current_category'] = next_category
            context.user_data['current_question_index'] = 0
            return await ask_next_medical_question(update, context)
        else:
            # All categories completed
            return await prepare_final_summary(update, context)
    
    # Continue with next question in current category
    return await ask_next_medical_question(update, context)

async def prepare_final_summary(update, context):
    # Prepare patient data including medical history if available
    patient_data = {
        'answers': context.user_data.get('answers', {}),
        'extra_info': context.user_data.get('extra_info', ''),
        'medical_history': context.user_data.get('medical_history', {}),
        'name': context.user_data.get('patient_info', {}).get('name', 'بدون نام'),
        'age': context.user_data.get('patient_info', {}).get('age', 'نامشخص'),
        'gender': context.user_data.get('patient_info', {}).get('gender', 'نامشخص'),
        'user_id': update.message.from_user.id,
        'date': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    
    context.user_data['patient_data'] = patient_data
    
    summary = "📋 خلاصه اطلاعات ثبت شده:\n\n"
    
    if context.user_data.get('patient_info'):
        summary += (
            f"👤 نام: {patient_data['name']}\n"
            f"📅 سن: {context.user_data['patient_info'].get('age', 'نامشخص')}\n"
            f"⚧ جنسیت: {context.user_data['patient_info'].get('gender', 'نامشخص')}\n\n"
        )
    
    if patient_data.get('medical_history'):
        summary += "📚 اطلاعات تکمیلی پزشکی ثبت شده است\n\n"
    
    summary += (
        "🔒 اطلاعات شما به صورت محرمانه نگهداری می‌شود.\n\n"
        "آیا مایل هستید اطلاعات شما برای دریافت تشخیص به سیستم هوشمند ارسال شود؟"
    )
    
    consent_buttons = ReplyKeyboardMarkup([
        ['بله، اطلاعات ارسال شود'],
        ['خیر، فرآیند متوقف شود']
    ], resize_keyboard=True)
    
    await update.message.reply_text(summary, reply_markup=consent_buttons)
    return DIAGNOSE

# Add this function before diagnose_disease
def check_api_health():
    """Check if Mistral API is responsive and properly configured"""
    try:
        # Try making a minimal test call to Mistral API
        response = call_language_model("test")
        if response and not "خطا" in response:
            return True, "API available"
        return False, "API not responding properly"
    except Exception as e:
        error_msg = str(e)
        if "quota exceeded" in error_msg.lower():
            return False, "API quota exceeded"
        return False, f"API error: {error_msg}"

async def diagnose_disease(update, context):
    """Enhanced disease diagnosis with better error handling"""
    user_response = update.message.text
    
    if user_response == 'خیر، فرآیند متوقف شود':
        await update.message.reply_text(
            "فرآیند تشخیص متوقف شد.\n"
            "هر زمان که تمایل داشتید می‌توانید با /start مجدداً شروع کنید.",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END

    if user_response != 'بله، اطلاعات ارسال شود':
        return DIAGNOSE

    try:
        # Get user information
        user = update.message.from_user
        visit_timestamp = datetime.now()
        visit_code = generate_visit_code(user.id, visit_timestamp)
        visit_link = generate_visit_link(user.id, visit_timestamp)
        
        processing_message = await update.message.reply_text(
            "🔄 در حال تحلیل اطلاعات...\n"
            "لطفاً صبور باشید. این فرآیند ممکن است چند دقیقه طول بکشد."
        )
        
        # Format medical report
        patient_data = context.user_data.get('patient_data', {})
        medical_report = format_medical_report(patient_data, context.user_data)
        
        # Debug log
        print("Sending to AI model:", medical_report[:500] + "..." if len(medical_report) > 500 else medical_report)
        
        try:
            # Call language model with retries
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    ai_response = call_language_model(medical_report)
                    if ai_response and isinstance(ai_response, str) and len(ai_response) > 50:
                        break
                    print(f"Attempt {attempt + 1}: Invalid response from AI model")
                    if attempt == max_retries - 1:
                        raise Exception("Failed to get valid response from AI model")
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise
                    print(f"Attempt {attempt + 1} failed: {str(e)}")
                    await asyncio.sleep(2)  # Wait before retry
            
            if not ai_response:
                raise Exception("No response received from AI model")
            
            # Save visit data
            visit_data = {
                **patient_data,
                'diagnosis': ai_response,
                'visit_code': visit_code,
                'visit_timestamp': visit_timestamp.isoformat(),
                'visit_link': visit_link,
                'user_id': user.id
            }
            
            # Save to database
            save_visit_to_database(patient_data, ai_response, visit_code, visit_timestamp, visit_link)
            
            # Delete processing message
            await processing_message.delete()
            
            # Send formatted response
            response_message = (
                "✅ تحلیل علائم انجام شد\n\n"
                f"{ai_response}\n\n"
                "🔗 لینک اختصاصی این ویزیت:\n"
                f"{visit_link}\n\n"
                "⚠️ توجه مهم:\n"
                "• این نتایج فقط جنبه راهنمایی دارند\n"
                "• برای تشخیص قطعی حتماً به پزشک مراجعه کنید"
            )
            
            await update.message.reply_text(
                response_message,
                reply_markup=ReplyKeyboardMarkup([['شروع معاینه جدید']], resize_keyboard=True)
            )
            return GETTING_STARTED
            
        except Exception as model_error:
            print(f"AI model error: {str(model_error)}")
            raise Exception(f"خطا در پردازش توسط هوش مصنوعی: {str(model_error)}")
            
    except Exception as e:
        error_msg = str(e)
        print(f"Diagnosis error: {error_msg}")
        
        if "quota exceeded" in error_msg.lower():
            message = (
                "⚠️ متأسفانه سهمیه استفاده از سیستم هوش مصنوعی تکمیل شده است.\n"
                "لطفاً چند ساعت دیگر مجدداً تلاش کنید."
            )
        else:
            message = (
                "⚠️ متأسفانه در پردازش اطلاعات خطایی رخ داد.\n"
                "لطفاً چند دقیقه دیگر مجدداً تلاش کنید.\n"
                f"کد خطا: {error_msg[:100]}"
            )
        
        await update.message.reply_text(
            message,
            reply_markup=ReplyKeyboardMarkup([['🔙 بازگشت به منوی اصلی']], resize_keyboard=True)
        )
        return GETTING_STARTED

def extract_symptoms_from_answers(answers):
    """Extract symptoms from answers for the diagnosis section."""
    symptoms = []
    for question, data in answers.items():
        if isinstance(data, dict) and data.get('answer') == '✅':
            symptoms.append(data.get('description', question))
    return symptoms

def write_symptoms_in_diagnosis_section(patient_data):
    """Write symptoms in the diagnosis section."""
    symptoms = extract_symptoms_from_answers(patient_data.get('answers', {}))
    if symptoms:
        return "🔍 علائم گزارش شده:\n" + "\n".join(f"• {symptom}" for symptom in symptoms)
    return "🔍 علائم گزارش شده: هیچ علامتی گزارش نشده است."

def format_medical_report(patient_data, user_data):
    """Enhanced medical report formatting with structured sections"""
    report = f"""بیمار جدید با مشخصات زیر:

👤 اطلاعات پایه:
نام: {user_data['patient_info'].get('name', 'نامشخص')}
سن: {user_data['patient_info'].get('age', 'نامشخص')}
جنسیت: {user_data['patient_info'].get('gender', 'نامشخص')}

{write_symptoms_in_diagnosis_section(patient_data)}

💭 توضیحات تکمیلی بیمار:
{patient_data.get('extra_info', 'بدون توضیحات اضافی')}

📚 سوابق پزشکی:
"""
    # Add symptoms with better structure
    if patient_data.get('answers'):
        for section, answers in patient_data['answers'].items():
            if answers:  # Check if section has any answers
                report += f"\n▫️ {section}:\n"
                if isinstance(answers, list):
                    for answer in answers:
                        if isinstance(answer, dict) and answer.get('answer') == '✅':
                            report += f"• {answer.get('description', '')}\n"
                elif isinstance(answers, dict):
                    report += f"• {answers.get('description', '')}\n"

    # Add extra information if available
    if patient_data.get('extra_info'):
        report += f"\n💭 توضیحات تکمیلی بیمار:\n{patient_data['extra_info']}\n"

    # Add medical history if available
    if patient_data.get('medical_history'):
        report += "\n📚 سوابق پزشکی:\n"
        for category, data in patient_data['medical_history'].items():
            if isinstance(data, dict) and data:
                report += f"\n▫️ {category}:\n"
                for key, value in data.items():
                    if value and value not in ['-', 'ندارم']:
                        report += f"• {value}\n"

    # Add the system prompt at the end
    report += f"\n\n{SYSTEM_PROMPT}\n"
    return report

def save_visit_to_database(patient_data, diagnosis, visit_code, visit_timestamp, visit_link):
    """Save visit information to database with enhanced diagnosis storage"""
    # Ensure the diagnosis is properly structured with recommendations
    if not "توصیه‌های درمانی:" in diagnosis and not "توصیه‌ها:" in diagnosis:
        # Add recommendations section if missing
        diagnosis = diagnosis.rstrip() + "\n\nتوصیه‌های درمانی:\n" + extract_recommendations(diagnosis)
    
    visit_data = {
        **patient_data,
        'diagnosis': diagnosis,
        'visit_code': visit_code,
        'visit_timestamp': visit_timestamp.isoformat(),
        'visit_link': visit_link,
        'telegram_info': {
            'username': patient_data.get('telegram_username'),
            'first_name': patient_data.get('telegram_first_name'),
            'last_name': patient_data.get('telegram_last_name')
        }
    }
    
    os.makedirs(DB_FOLDER, exist_ok=True)
    file_path = os.path.join(DB_FOLDER, DB_FILE)
    
    try:
        if not os.path.exists(file_path):
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump([visit_data], f, ensure_ascii=False, indent=2)
        else:
            with open(file_path, 'r+', encoding='utf-8') as f:
                data = json.load(f)
                data.append(visit_data)
                f.seek(0)
                f.truncate()
                json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving to database: {str(e)}")
        raise

    # Update markdown file in parallel.
    update_markdown_report(visit_data)

def extract_recommendations(diagnosis):
    """Extract or generate recommendations from diagnosis text"""
    recommendations = []
    
    # Look for treatment-related keywords
    keywords = ['درمان', 'دارو', 'توصیه', 'پیشنهاد', 'مصرف']
    
    for line in diagnosis.split('\n'):
        for keyword in keywords:
            if keyword in line and not any(rec in line for rec in recommendations):
                recommendations.append(line.strip())
                break
    
    if not recommendations:
        recommendations.append("مراجعه به پزشک برای دریافت درمان مناسب")
    
    return "\n".join(f"• {rec}" for rec in recommendations)

async def send_diagnosis_response(update, diagnosis, visit_link):
    """Send formatted diagnosis response to user"""
    response_message = (
        "📋 نتیجه بررسی علائم شما:\n\n"
        f"{diagnosis}\n\n"
        "🔗 لینک اختصاصی این ویزیت:\n"
        f"{visit_link}\n\n"
        "⚠️ توجه مهم:\n"
        "• این نتایج فقط جنبه راهنمایی دارند\n"
        "• برای تشخیص قطعی حتماً به پزشک مراجعه کنید\n"
        "• در صورت وجود علائم حاد یا اورژانسی، سریعاً به مراکز درمانی مراجعه نمایید"
    )
    
    await update.message.reply_text(
        response_message,
        reply_markup=ReplyKeyboardMarkup([['شروع معاینه جدید']], resize_keyboard=True)
    )

async def cancel(update, context):
    await update.message.reply_text(
        "فرآیند لغو شد. برای شروع مجدد /start را بزنید.",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

async def handle_basic_info(update, context):
    """Handle basic info collection directly"""
    user_id = update.message.from_user.id
    existing_info = await check_existing_info(user_id)
    
    if (existing_info):
        context.user_data['patient_info'] = existing_info
        # Initialize section answers
        context.user_data['answers'] = {}
        context.user_data['current_section'] = 0
        context.user_data['sections'] = get_sections()
        context.user_data['all_questions'] = parse_questions()
        
        section = context.user_data['sections'][0]
        section_name = section['name']
        
        explanation = (
            "⚕️ راهنمای پاسخ‌دهی:\n"
            "✅ = بله، علائمی در این بخش دارم\n"
            "❌ = خیر، علائمی در این بخش ندارم\n\n"
            "لطفاً مشخص کنید در کدام بخش‌های بدن علائم دارید:\n\n"
        )
        await update.message.reply_text(explanation)
        await update.message.reply_text(
            f"بخش: {section_name}\n\n"
            "آیا در این بخش علائمی دارید؟",
            reply_markup=ReplyKeyboardMarkup([['✅', '❌']], resize_keyboard=True)
        )
        return GET_SECTION_ANSWERS
    else:
        return await request_patient_name(update, context)

# Update QUESTIONS format and parsing
def parse_section_questions(section_text):
    """Parse questions from a single section text"""
    lines = section_text.strip().split('\n')
    section_title = lines[0].strip() if lines else ""
    questions = []
    
    for line in lines:
        if '✅❌' in line:
            # Extract question text after the checkboxes
            question_text = line.replace('✅❌', '').strip()
            if ':' in question_text:
                q_text, q_desc = [x.strip() for x in question_text.split(':', 1)]
                questions.append({
                    'text': q_text,
                    'description': q_desc
                })
    
    return {
        'title': section_title,
        'questions': questions
    }

def parse_all_sections():
    """Parse all sections and their questions"""
    sections = []
    for section_text in QUESTIONS:
        parsed = parse_section_questions(section_text)
        if parsed['title'] and parsed['questions']:
            sections.append(parsed)
    return sections

# Update conversation states
GETTING_STARTED, GET_BASIC_INFO, GET_NAME, GET_AGE, GET_GENDER = range(5)
SECTION_CHECK, QUESTION_FLOW, SECTION_COMPLETE = range(5, 8)

# Add new handlers for section navigation
async def start_section_flow(update, context):
    """Initialize and start the section flow"""
    context.user_data['sections'] = parse_all_sections()
    context.user_data['current_section'] = 0
    context.user_data['answers'] = {}
    
    return await check_section(update, context)

async def check_section(update, context):
    """Check if current section has symptoms"""
    # Initialize if not exists
    if 'sections' not in context.user_data:
        context.user_data['sections'] = get_sections()
    if 'current_section' not in context.user_data:
        context.user_data['current_section'] = 0
    if 'answers' not in context.user_data:
        context.user_data['answers'] = {}
    
    # Safety check for section index
    if context.user_data['current_section'] >= len(context.user_data['sections']):
        return await handle_sections_completion(update, context)
        
    current = context.user_data['sections'][context.user_data['current_section']]
    
    await update.message.reply_text(
        f"🔍 بخش {context.user_data['current_section'] + 1}/{len(context.user_data['sections'])}:\n"
        f"{current['title']}\n\n"
        "آیا در این بخش علائمی دارید؟",
        reply_markup=ReplyKeyboardMarkup([['✅', '❌']], resize_keyboard=True)
    )
    return SECTION_CHECK

async def handle_section_check(update, context):
    """Process section check response"""
    answer = update.message.text
    
    # Validate answer format
    if answer not in ['✅', '❌']:
        await update.message.reply_text("لطفاً از دکمه‌های ✅ یا ❌ استفاده کنید.")
        return SECTION_CHECK
    
    # Safety checks
    if ('current_section' not in context.user_data or 
        'sections' not in context.user_data or
        context.user_data['current_section'] >= len(context.user_data['sections'])):
        # Reset state if invalid
        context.user_data['current_section'] = 0
        context.user_data['sections'] = get_sections()
        return await check_section(update, context)
    
    current_section = context.user_data['sections'][context.user_data['current_section']]
    current_section_title = current_section['title']
    
    # Find section data
    current_section_data = next(
        (section for section in QUESTIONS if section.get('title') == current_section_title),
        None
    )
    
    if answer == '✅' and current_section_data and 'symptoms' in current_section_data:
        # Store section responses
        context.user_data['current_section_symptoms'] = current_section_data['symptoms']
        context.user_data['current_symptom_index'] = 0
        return await ask_section_question(update, context)
    else:
        # Move to next section
        context.user_data['current_section'] += 1
        return await check_section(update, context)

async def ask_section_question(update, context):
    """Ask questions for sections with symptoms"""
    # Safety checks
    if ('current_section_symptoms' not in context.user_data or
        'current_symptom_index' not in context.user_data):
        context.user_data['current_section'] += 1
        return await check_section(update, context)
    
    current_symptoms = context.user_data['current_section_symptoms']
    current_index = context.user_data['current_symptom_index']
    
    # Check if we've completed all questions
    if current_index >= len(current_symptoms):
        context.user_data['current_section'] += 1
        return await check_section(update, context)
    
    current_section = context.user_data['sections'][context.user_data['current_section']]
    symptom = current_symptoms[current_index]
    
    await update.message.reply_text(
        f"🔹 {current_section['title']}\n"
        f"سؤال {current_index + 1}/{len(current_symptoms)}:\n\n"
        f"🔍 {symptom.get('description', symptom)}",
        reply_markup=ReplyKeyboardMarkup([['✅', '❌']], resize_keyboard=True)
    )
    return GET_ANSWERS

async def handle_question_answer(update, context):
    """Process question answers"""
    answer = update.message.text
    
    if answer not in ['✅', '❌']:
        return await ask_section_question(update, context)
    
    # Validate section index
    if ('current_section' not in context.user_data or 
        'sections' not in context.user_data or
        context.user_data['current_section'] >= len(context.user_data['sections'])):
        # Reset to start if indices are invalid
        context.user_data['current_section'] = 0
        return await check_section(update, context)
        
    current_section = context.user_data['sections'][context.user_data['current_section']]
    
    # Validate symptom index
    if ('current_section_symptoms' not in context.user_data or
        'current_symptom_index' not in context.user_data or
        context.user_data['current_symptom_index'] >= len(context.user_data['current_section_symptoms'])):
        # Move to next section if symptom indices are invalid
        context.user_data['current_section'] += 1
        return await check_section(update, context)
    
    current_symptom = context.user_data['current_section_symptoms'][context.user_data['current_symptom_index']]
    
    if answer == '✅':
        # Save positive answers
        if 'answers' not in context.user_data:
            context.user_data['answers'] = {}
            
        section_answers = context.user_data['answers'].setdefault(current_section['title'], [])
        section_answers.append({
            'description': current_symptom['description'],
            'answer': answer
        })
    
    # Move to next symptom
    context.user_data['current_symptom_index'] += 1
    return await ask_section_question(update, context)

async def complete_sections(update, context):
    """Handle completion of all sections"""
    summary = "✅ تمام بخش‌ها بررسی شدند.\n\n"
    
    # Generate summary of positive answers
    for section, answers in context.user_data['answers'].items():
        if answers:
            summary += f"🔹 {section}:\n"
            for q_text, data in answers.items():
                if data['answer'] == '✅':
                    summary += f"  • {q_text}\n"
            summary += "\n"
    
    await update.message.reply_text(summary)
    # Continue to next stage (e.g., GET_EXTRA_INFO)
    return GET_EXTRA_INFO

async def handle_version_selection(update, context):
    choice = update.message.text
    selected_visit = context.user_data.get('selected_visit')
    
    if choice == '🔙 بازگشت به لیست ویزیت‌ها':
        return await show_visit_history(update, context)
    
    if not selected_visit:
        await update.message.reply_text(
            "اطلاعات ویزیت در دسترس نیست.",
            reply_markup=ReplyKeyboardMarkup([['🔙 بازگشت به منوی اصلی']], resize_keyboard=True)
        )
        return VIEW_HISTORY
    
    visit_date = datetime.fromisoformat(selected_visit['visit_timestamp']).strftime("%Y-%m-%d %H:%M")
    visit_code = selected_visit.get('visit_code', 'نامشخص')
    
    if choice == 'نسخه تشخیص':
        # Build symptoms summary with sorted reported answers
        symptoms_summary = "🔍 علائم گزارش شده:\n"
        if selected_visit.get('extra_info'):
            symptoms_summary += f"\n💭 توضیحات تکمیلی:\n{selected_visit['extra_info']}\n"
        
        answers = selected_visit.get("answers", {})
        if answers:
            symptoms = []
            for question, data in answers.items():
                if isinstance(data, dict):
                    symptoms.append((data.get('description', question), data.get('answer', '')))
                else:
                    symptoms.append((question, data))
            symptoms.sort(key=lambda x: x[0])
            symptom_list = ""
            for desc, ans in symptoms:
                symptom_list += f"• {desc} → {ans}\n"
            if not symptom_list.strip():
                symptoms_summary += "\n🔹 گزارش علائم: هیچ علامتی گزارش نشده است.\n"
            else:
                symptoms_summary += "\n🔹 گزارش علائم:\n" + symptom_list + "\n"
        else:
            symptoms_summary += "\n🔹 گزارش علائم: هیچ علامتی گزارش نشده است.\n"
        
        diagnosis_text = (
            f"📋 گزارش تشخیص (کد ویزیت: {visit_code})\n"
            f"📅 تاریخ ویزیت: {visit_date}\n\n"
            f"{symptoms_summary}\n"
            f"👨‍⚕️ تشخیص هوش مصنوعی:\n"
            f"{selected_visit.get('diagnosis', 'تشخیصی ثبت نشده است.')}\n\n"
            f"🔗 لینک ویزیت:\n{selected_visit.get('visit_link', 'موجود نیست')}\n\n"
            "⚠️ یادآوری: این تشخیص صرفاً جنبه راهنمایی دارد و جایگزین مراجعه به پزشک نیست."
        )
        
        if len(diagnosis_text) > 4096:
            parts = [diagnosis_text[i:i+4096] for i in range(0, len(diagnosis_text), 4096)]
            for part in parts:
                await update.message.reply_text(part)
        else:
            await update.message.reply_text(
                diagnosis_text,
                reply_markup=ReplyKeyboardMarkup([['🔙 بازگشت به لیست ویزیت‌ها']], resize_keyboard=True)
            )
    elif choice == 'نسخه تجویز':
        # Extract recommendations from diagnosis
        diagnosis = selected_visit.get('diagnosis', '')
        recommendations = []
        
        # Look for different recommendation sections
        sections = [
            ('توصیه‌های ایمن:', 'توصیه‌های درمانی:'),
            ('توصیه‌های درمانی:', '⚠️'),
            ('💊 توصیه‌ها:', '\n\n'),
            ('توصیه‌ها:', '\n\n')
        ]
        
        for start_marker, end_marker in sections:
            if start_marker in diagnosis:
                try:
                    start_idx = diagnosis.index(start_marker) + len(start_marker)
                    if end_marker in diagnosis[start_idx:]:
                        end_idx = diagnosis.index(end_marker, start_idx)
                        recommendation = diagnosis[start_idx:end_idx].strip()
                        if recommendation:
                            recommendations.append(recommendation)
                except ValueError:
                    continue
        
        prescription_text = (
            f"👨‍⚕️ نسخه تجویزی (کد ویزیت: {visit_code})\n"
            f"📅 تاریخ ویزیت: {visit_date}\n\n"
        )
        
        if recommendations:
            prescription_text += "💊 توصیه‌های درمانی:\n"
            for i, rec in enumerate(recommendations, 1):
                prescription_text += f"{i}. {rec}\n"
        else:
            prescription_text += "❌ توصیه‌ای در گزارش تشخیص یافت نشد.\n"
        
        prescription_text += (
            "\n⚠️ توجه:\n"
            "• این توصیه‌ها عمومی هستند\n"
            "• برای استفاده از هر دارو با پزشک مشورت کنید\n"
            "• در صورت تشدید علائم به پزشک مراجعه کنید"
        )
        
        await update.message.reply_text(
            prescription_text,
            reply_markup=ReplyKeyboardMarkup([['🔙 بازگشت به لیست ویزیت‌ها']], resize_keyboard=True)
        )
    
    else:
        await update.message.reply_text(
            "لطفاً یکی از گزینه‌های موجود را انتخاب کنید.",
            reply_markup=ReplyKeyboardMarkup([
                ['نسخه تشخیص'],
                ['نسخه تجویز'],
                ['🔙 بازگشت به لیست ویزیت‌ها']
            ], resize_keyboard=True)
        )
    
    return SELECT_VISIT_VERSION

async def handle_visit_link(update, context):
    """Handle visiting a patient record via deep link."""
    try:
        user = update.message.from_user
        command_parts = update.message.text.split()
        if len(command_parts) != 2:
            raise ValueError("Invalid visit link format")
            
        # Extract and decode visit identifier
        encoded_data = command_parts[1].replace('visit_', '')
        padded_data = encoded_data + '=' * (-len(encoded_data) % 4)
        decoded_data = base64.urlsafe_b64decode(padded_data).decode()
        patient_id, date_time = decoded_data.split('-', 1)
        
        # Load visit details
        visit = await get_visit_details(int(patient_id), date_time)
        if not visit:
            raise ValueError("Visit record not found")

        # Store visit in context for further access
        context.user_data['selected_visit'] = visit
        
        # Format visit information for medical professionals
        medical_info = format_medical_info(visit)
        
        # Create user-friendly buttons
        buttons = [
            ['📋 مشاهده جزئیات تشخیص'],
            ['💊 مشاهده توصیه‌های درمانی'],
            ['🔙 بازگشت به منوی اصلی']
        ]
        
        await update.message.reply_text(
            medical_info,
            reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True)
        )
        return SELECT_VISIT_VERSION

    except Exception as e:
        print(f"Error handling visit link: {e}")
        await update.message.reply_text(
            "❌ خطا در دسترسی به اطلاعات ویزیت.\n"
            "لطفاً از صحت لینک اطمینان حاصل کنید.",
            reply_markup=ReplyKeyboardMarkup([['🔙 بازگشت به منوی اصلی']], resize_keyboard=True)
        )
        return GETTING_STARTED

def format_medical_info(visit):
    """Format visit information for medical professionals."""
    visit_date = datetime.fromisoformat(visit['visit_timestamp']).strftime("%Y-%m-%d %H:%M")
    
    info = (
        f"📋 اطلاعات ویزیت پزشکی\n"
        f"🔖 کد ویزیت: {visit.get('visit_code', 'نامشخص')}\n"
        f"📅 تاریخ مراجعه: {visit_date}\n\n"
        f"👤 مشخصات بیمار:\n"
        f"نام: {visit.get('name', 'نامشخص')}\n"
    )
    
    if visit.get('medical_history'):
        info += "\n📚 سوابق پزشکی ثبت شده است"
    
    if visit.get('answers'):
        info += "\n🔍 علائم اصلی ثبت شده است"
    
    info += (
        "\n\n⚕️ لطفاً برای مشاهده جزئیات تشخیص یا "
        "توصیه‌های درمانی، از دکمه‌های زیر استفاده کنید."
    )
    
    return info

async def get_visit_details(user_id, timestamp):
    """Retrieve visit details from database"""
    if os.path.exists(os.path.join(DB_FOLDER, DB_FILE)):
        try:
            with open(os.path.join(DB_FOLDER, DB_FILE), 'r', encoding='utf-8') as f:
                visits = json.load(f)
                for visit in visits:
                    if (visit.get('user_id') == user_id and 
                        visit.get('visit_timestamp', '').startswith(timestamp)):
                        return visit
        except Exception as e:
            print(f"Error reading visit database: {e}")
    return None

async def send_visit_details(update, visit_info):
    """Format and send visit information"""
    try:
        # Get patient info
        patient_info = None
        if os.path.exists(PATIENT_INFO_DB):
            with open(PATIENT_INFO_DB, 'r', encoding='utf-8') as f:
                patients = json.load(f)
                patient_info = next(
                    (p for p in patients if p['user_id'] == visit_info['user_id']),
                    None
                )

        # Format visit details
        visit_date = datetime.fromisoformat(visit_info['visit_timestamp']).strftime("%Y-%m-%d %H:%M")
        
        header = (
            f"📋 اطلاعات ویزیت\n"
            f"📅 تاریخ: {visit_date}\n"
            f"🔖 کد ویزیت: {visit_info.get('visit_code', 'نامشخص')}\n\n"
        )

        if patient_info:
            patient_details = (
                f"👤 اطلاعات بیمار:\n"
                f"نام: {patient_info['name']}\n"
                f"سن: {patient_info['age']}\n"
                f"جنسیت: {patient_info['gender']}\n\n"
            )
        else:
            patient_details = "❌ اطلاعات بیمار در دسترس نیست\n\n"

        # Format symptoms
        symptoms = "🔍 علائم گزارش شده:\n"
        for section, answers in visit_info.get('answers', {}).items():
            if isinstance(answers, dict) and answers.get('answer') == '✅':
                symptoms += f"• {answers.get('description', section)}\n"

        # Add extra info if available
        if visit_info.get('extra_info'):
            symptoms += f"\n💬 توضیحات تکمیلی:\n{visit_info['extra_info']}\n"

        # Add medical history if available
        medical_history = ""
        if visit_info.get('medical_history'):
            medical_history = "\n📚 سوابق پزشکی:\n"
            for category, items in visit_info['medical_history'].items():
                if isinstance(items, dict) and items:
                    medical_history += f"\n▫️ {category}:\n"
                    for key, value in items.items():
                        if value and value not in ['-', 'ندارم']:
                            medical_history += f"  • {value}\n"

        # Add AI diagnosis if available
        diagnosis = ""
        if visit_info.get('diagnosis'):
            diagnosis = f"\n👨‍⚕️ تشخیص هوش مصنوعی:\n{visit_info['diagnosis']}\n"

        # Combine all sections
        full_report = header + patient_details + symptoms + medical_history + diagnosis

        # Split long messages if needed
        if len(full_report) > 4096:
            parts = [full_report[i:i+4096] for i in range(0, len(full_report), 4096)]
            for part in parts:
                await update.message.reply_text(part)
        else:
            await update.message.reply_text(full_report)

    except Exception as e:
        print(f"Error formatting visit details: {e}")
        await update.message.reply_text(
            "❌ خطا در نمایش اطلاعات ویزیت.",
            reply_markup=ReplyKeyboardMarkup([['🔙 بازگشت به منوی اصلی']], resize_keyboard=True)
        )

def update_markdown_report(visit_data):
    """
    Append visit report to markdown file.
    The report includes:
      - Visit Code & Timestamp
      - Patient name
      - Diagnosis details
      - Prescription (extracted using recommendations markers)
    """
    # Use the correct reports folder path
    reports_folder = r"C:\Users\Administrator\Desktop\Dr_Agent - With MistralAI\Database\reports"
    os.makedirs(reports_folder, exist_ok=True)
    
    md_path = os.path.join(reports_folder, "visit_reports.md")
    
    try:
        # Create file with header if it doesn't exist
        if not os.path.exists(md_path):
            with open(md_path, "w", encoding="utf-8") as md_file:
                md_file.write("# Visit Reports Repository\n\n"
                            "This file stores visit details including diagnosis and prescription data.\n\n"
                            "---\n")
        
        # Extract age and gender ensuring complete patient data
        age = visit_data.get('age') or visit_data.get('patient_info', {}).get('age', 'نامشخص')
        gender = visit_data.get('gender') or visit_data.get('patient_info', {}).get('gender', 'نامشخص')
        try:
            visit_date = datetime.fromisoformat(visit_data.get('visit_timestamp', '')).strftime("%Y-%m-%d %H:%M")
        except:
            visit_date = datetime.now().strftime("%Y-%m-%d %H:%M")
            
        # Create a detailed visit report entry including age and gender
        report_entry = (
            f"\n\n## Visit Report - {visit_data.get('visit_code', 'N/A')}\n"
            f"**Date:** {visit_date}\n"
            f"**Patient:** {visit_data.get('name', 'نامشخص')}\n"
            f"**Gender:** {gender}\n"
            f"**Age:** {age}\n\n"
        )
        
        # Add symptoms section if available
        symptoms_text = format_symptoms_for_markdown(visit_data.get('answers', {}))
        if symptoms_text:
            report_entry += f"### Symptoms\n{symptoms_text}\n\n"
        
        # Add additional information if available
        extra_info = visit_data.get('extra_info')
        if (extra_info):
            report_entry += f"### Additional Information\n{extra_info}\n\n"
        
        # Add medical history if available
        medical_history = visit_data.get('medical_history', {})
        if medical_history:
            report_entry += "### Medical History\n"
            for category, data in medical_history.items():
                if isinstance(data, dict) and data:
                    report_entry += f"\n#### {category}\n"
                    for key, value in data.items():
                        if value and value not in ['-', 'ندارم']:
                            report_entry += f"- {value}\n"
            report_entry += "\n"
        
        # Extract prescription details from diagnosis
        diagnosis = visit_data.get('diagnosis', '')
        prescription = ""
        
        # Try different markers to extract prescription
        markers = [
            ('توصیه‌های درمانی:', '⚠️'),
            ('توصیه‌های درمانی:', '\n\n'),
            ('توصیه‌ها:', '\n\n'),
            ('💊 توصیه‌ها:', '\n\n')
        ]
        
        for start_marker, end_marker in markers:
            if start_marker in diagnosis:
                try:
                    start_idx = diagnosis.index(start_marker) + len(start_marker)
                    if end_marker in diagnosis[start_idx:]:
                        end_idx = diagnosis.index(end_marker, start_idx)
                        prescription = diagnosis[start_idx:end_idx].strip()
                        break
                except ValueError:
                    continue
        
        # If no prescription found using markers, use recommendation extraction
        if not prescription:
            prescription = extract_recommendations(diagnosis)
        
        # Add diagnosis and prescription
        report_entry += (
            f"### Diagnosis\n{diagnosis}\n\n"
            f"### Prescription\n{prescription}\n\n"
            "---\n"
        )
        
        # Append the report to the file
        with open(md_path, "a", encoding="utf-8") as md_file:
            md_file.write(report_entry)
            
        print(f"Visit report successfully saved to {md_path}")
        
    except Exception as e:
        print(f"Error updating markdown report: {e}")
        # Create error log for debugging
        error_log_path = os.path.join(reports_folder, "error_log.txt")
        with open(error_log_path, "a", encoding="utf-8") as error_file:
            error_file.write(f"\n[{datetime.now()}] Error: {str(e)}\n")
            error_file.write(f"Failed visit code: {visit_data.get('visit_code', 'N/A')}\n")

def format_symptoms_for_markdown(answers):
    """Helper function to format symptoms for markdown, including all responses"""
    if not answers:
        return "No symptoms recorded."
    
    formatted_symptoms = []
    for question, data in answers.items():
        if isinstance(data, dict):
            section = data.get('section', 'General')
            description = data.get('description', question)
            response = data.get('answer', '')
            formatted_symptoms.append(f"- **{section}:** {description} → **{response}**")
        else:
            formatted_symptoms.append(f"- {question}: {data}")
    
    return "\n".join(formatted_symptoms)

def main():
    # Build application using ApplicationBuilder
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CommandHandler('start', handle_deep_link, filters.Regex(r'visit_\w+'))
        ],
        states={
            GETTING_STARTED: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_start_choice)
            ],
            VIEW_HISTORY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_visit_selection)
            ],
            SELECT_VISIT_VERSION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_version_selection)
            ],
            GET_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_name)
            ],
            GET_AGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_age)
            ],
            GET_GENDER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_gender_and_proceed)
            ],
            GET_SECTION_ANSWERS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_section_answers)
            ],
            GET_ANSWERS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_answers)
            ],
            GET_EXTRA_INFO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_data)
            ],
            CONFIRM_EXTRA_INFO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_extra_info_confirmation)
            ],
            ASK_FOR_MEDICAL_HISTORY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_medical_history_choice)
            ],
            GET_MEDICAL_HISTORY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_medical_history_answer)
            ],
            GET_BASIC_INFO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_basic_info)
            ],
            GET_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_name)
            ],
            GET_AGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_age)
            ],
            GET_GENDER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_extra_info_confirmation)
            ],
            ASK_FOR_MEDICAL_HISTORY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_medical_history_choice)
            ],
            GET_MEDICAL_HISTORY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_medical_history_answer)
            ],
            DIAGNOSE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, diagnose_disease)
            ],
            SECTION_CHECK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_section_check)
            ],
            QUESTION_FLOW: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_question_answer)
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    application.add_handler(conv_handler)
    
    # Add handler for visit links
    application.add_handler(MessageHandler(
        filters.Regex(r'(/visit|https://dr-agent\..*?/visit/)'), 
        handle_visit_link
    ))
    
    print("Starting bot...")
    # Use a list of allowed update types instead of Update.ALL_TYPES
    application.run_polling(allowed_updates=['message', 'callback_query'])

if __name__ == "__main__":
    main()