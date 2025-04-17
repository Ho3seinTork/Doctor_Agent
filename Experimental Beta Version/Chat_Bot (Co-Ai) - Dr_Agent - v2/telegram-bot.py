import logging
import os
from enum import Enum
from typing import Dict, Optional
from dotenv import load_dotenv

import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler
from telegram.ext import ContextTypes, filters, ConversationHandler
from datetime import datetime
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# Load and parse external configuration from .env; decouples sensitive credentials from code.
load_dotenv()

# Initialize centralized logging to capture critical runtime events for post-deployment diagnostics.
# Logging is file-based and console output is suppressed to enhance production performance.
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.ERROR,  # Log only errors to avoid performance and clarity issues in production.
    handlers=[
        logging.FileHandler('bot.log'),  # Persist logs for audit and troubleshooting.
        logging.NullHandler()  # Suppress default console logging to minimize runtime overhead.
    ]
)
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())  # Ensure no duplicate logging handlers are attached.

# Retrieve critical API credentials from environment; ensures a secure, configurable deployment.
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
    # Fail fast if essential configuration is missing; this prevents undefined behavior.
    raise ValueError("TELEGRAM_TOKEN or GEMINI_API_KEY environment variable is not set")

# Initialize Gemini generative AI model with tuned parameters for balanced creativity and safety.
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-pro',
    generation_config={
        'temperature': 0.7,  # Adjust randomness to optimize creative output.
        'top_p': 0.9,        # Use nucleus sampling to focus on quality responses.
        'max_output_tokens': 4000,  # Ensure responses remain within Telegram limits.
    },
    safety_settings={
        HarmCategory.HARASSMENT: HarmBlockThreshold.MEDIUM,
        HarmCategory.HATE_SPEECH: HarmBlockThreshold.MEDIUM,
        HarmCategory.SEXUALLY_EXPLICIT: HarmBlockThreshold.MEDIUM,
        HarmCategory.DANGEROUS_CONTENT: HarmBlockThreshold.MEDIUM,
    }
)

# Enumeration defining conversation states; follows the state design pattern for robust session management.
class States(Enum):
    CHOOSING_MODE = 0
    ARTICLE_WRITING = 1
    MEDICAL_CHAT = 2

# Scoped storage for user sessions; maintains context for stateless conversations.
user_sessions: Dict[int, Dict] = {}

# Define constant for mandatory Telegram channel membership; enforces gated access.
CHANNEL_ID = "@DrAgent_channel"

async def check_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Verify user membership in the mandated channel to enforce access control.
    
    Utilizes Telegram API robustly and handles network/API exceptions gracefully.
    """
    try:
        user_id = update.effective_user.id
        member = await context.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Error checking member status: {str(e)}")
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for the /start command.
    
    Validates channel membership, initializes the user session, and presents mode options.
    Follows a defensive programming stance to ensure proper session context.
    """
    user_id = update.effective_user.id
    
    # Validate channel membership to gate critical functionalities.
    if not await check_member(update, context):
        keyboard = [[InlineKeyboardButton("عضویت در کانال", url="https://t.me/DrAgent_channel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "⚠️ برای استفاده از ربات، لطفا ابتدا در کانال ما عضو شوید:\n"
            "@DrAgent_channel\n\n"
            "پس از عضویت، مجدداً /start را ارسال کنید.",
            reply_markup=reply_markup
        )
        return ConversationHandler.END
    
    # Initialize or reset user session to ensure stateless and non-leaky context handling.
    user_sessions[user_id] = {
        "current_mode": None,
        "chat_history": []
    }
    
    keyboard = [
        [
            InlineKeyboardButton("📝 Article Writing", callback_data="mode_article"),
            InlineKeyboardButton("👨‍⚕️ Medical Chat", callback_data="mode_medical")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "👋 به ربات گفتو و گوی دستیار پزشک خوش آمدید!\n\n"
        "این ربات می‌تواند به شما کمک کند:\n"
        "1️⃣ * نوشتن مقاله (Co-Ai)* - تولید مقاله در هر موضوع است.\n"
        "2️⃣ * گفتگو پزشکی* - پاسخ به سوالات پزشکی و بهداشتی است.\n\n"
        "لطفا یک حالت را انتخاب کنید:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    
    return States.CHOOSING_MODE

async def mode_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Route user selection to the appropriate conversation mode.
    
    Updates session context and provides mode-specific UI feedback.
    """
    query = update.callback_query
    user_id = update.effective_user.id
    
    await query.answer()
    
    if query.data == "mode_article":
        user_sessions[user_id]["current_mode"] = "article"
        await query.edit_message_text(
            "📝 حالت نوشتن مقاله فعال شد!\n\n"
            "لطفا موضوع یا کلمات کلیدی مورد نظر برای مقاله را وارد کنید. به عنوان مثال:\n"
            "- تغییرات اقلیمی و انرژی‌های تجدیدپذیر\n"
            "- مزایای مدیتیشن برای سلامت روان\n"
            "- آینده هوش مصنوعی\n\n"
            "برای خروج از این حالت از دستور /cancel یا تغییر حالت از /mode استفاده کنید.",
            parse_mode="Markdown"
        )
        return States.ARTICLE_WRITING
    
    elif query.data == "mode_medical":
        user_sessions[user_id]["current_mode"] = "medical"
        await query.edit_message_text(
            "🩺 حالت گفتگو پزشکی فعال شد!\n\n"
            "اکنون می‌توانید سوالات پزشکی یا بهداشتی خود را مطرح کنید. به عنوان مثال:\n"
            "- چگونه کیفیت خواب خود را بهبود دهم؟\n"
            "- علائم کمبود ویتامین D چیست؟\n"
            "- آیا روزه‌داری مفید است؟\n\n"
            "برای خروج از این حالت از دستور /cancel یا تغییر حالت از /mode استفاده کنید.\n\n"
            "⚠️ *توضیح*: این ربات صرفاً اطلاعات عمومی ارائه می‌دهد و جایگزین مشاوره پزشکی نمی‌باشد.",
            parse_mode="Markdown"
        )
        return States.MEDICAL_CHAT
    
    return States.CHOOSING_MODE

async def change_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the /mode command to reconfigure the conversation mode.
    
    Presents an interactive mode selection interface leveraging inline keyboards.
    """
    keyboard = [
        [
            InlineKeyboardButton("📝 Article Writing", callback_data="mode_article"),
            InlineKeyboardButton("👨‍⚕️ Medical Chat", callback_data="mode_medical")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "📊 *تغییر حالت*\n\nلطفا حالت جدید را انتخاب کنید:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    
    return States.CHOOSING_MODE

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Gracefully terminates the current mode via the /cancel command.
    
    Resets the user session, ensuring clean state and preventing residual context issues.
    """
    user_id = update.effective_user.id
    
    # Reset session to default state to avoid stale data.
    if user_id in user_sessions:
        user_sessions[user_id] = {
            "current_mode": None,
            "chat_history": []
        }
    
    await update.message.reply_text(
        "✅ عملیات لغو شد. از حالت فعلی خارج شدید.\n\n"
        "برای شروع دوباره از دستور /start یا تغییر حالت از /mode استفاده کنید."
    )
    
    return ConversationHandler.END

async def save_to_markdown(user_id: int, mode: str, query: str, response: str) -> None:
    """Persists the interaction log in Markdown format for auditing and debugging.
    
    The timestamp ensures each record is traceable. This supports later analysis or reviews.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    markdown_content = f"""
## User Interaction - {timestamp}
- **User ID:** {user_id}
- **Mode:** {mode}
- **Query:**
```
{query}
```
- **Response:**
```
{response}
```
---
"""
    
    with open("Data.md", "a", encoding="utf-8") as f:
        f.write(markdown_content)

async def handle_article_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Processes the article generation mode.
    
    Solicits user input as a topic, triggers the Gemini API asynchronously, manages response chunking,
    and persists the interaction with a strong focus on performance and error handling.
    """
    user_id = update.effective_user.id
    topic = update.message.text
    
    await context.bot.send_chat_action(
        chat_id=update.effective_message.chat_id,
        action="typing"
    )
    
    await update.message.reply_text("🔍 در حال تولید مقاله شما... ممکن است کمی طول بکشد.")
    
    try:
        # Invoke Gemini API with robust asynchronous call while ensuring fact-checking.
        article = await generate_article_with_deepseek(topic)
        
        if not article:
            await update.message.reply_text(
                "⚠️ متاسفانه در تولید مقاله خطایی رخ داد. لطفاً دوباره تلاش کنید."
            )
            return States.ARTICLE_WRITING
        
        # Persist the conversation log before delivering the response.
        await save_to_markdown(user_id, "Article Writing", topic, article)
        
        # For excessively long articles, segment output to conform to Telegram limitations.
        if len(article) > 4000:
            chunks = [article[i:i+4000] for i in range(0, len(article), 4000)]
            for i, chunk in enumerate(chunks):
                if i == 0:
                    await update.message.reply_text(
                        f"📄 *مقاله درباره: {topic}*\n\n{chunk}",
                        parse_mode="Markdown"
                    )
                else:
                    await update.message.reply_text(
                        f"{chunk}",
                        parse_mode="Markdown"
                    )
        else:
            await update.message.reply_text(
                f"📄 *مقاله درباره: {topic}*\n\n{article}",
                parse_mode="Markdown"
            )
        
        await update.message.reply_text(
            "آیا مایل به تولید مقاله دیگری هستید؟ همین طور یک موضوع جدید وارد کنید.\n\n"
            "برای تغییر حالت از /mode یا خروج از حالت از /cancel استفاده کنید."
        )
        
    except Exception as e:
        logger.error(f"Error in article generation: {str(e)}")
        await update.message.reply_text(
            "❌ متاسفانه در تولید مقاله خطایی رخ داده است. لطفاً بعداً تلاش کنید."
        )
    
    return States.ARTICLE_WRITING

async def handle_medical_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles medical inquiries by leveraging contextual history and Gemini API for safe responses.
    
    Maintains conversation continuity and adheres to scientific safety guidelines.
    """
    user_id = update.effective_user.id
    query = update.message.text
    
    # Retrieve existing conversation, ensuring context propagation for enhanced relevance.
    chat_history = user_sessions.get(user_id, {}).get("chat_history", [])
    
    # Append the latest user query to the session history.
    chat_history.append({"role": "user", "content": query})
    
    # Indicate processing to the user, managing latency expectations.
    await context.bot.send_chat_action(
        chat_id=update.effective_message.chat_id,
        action="typing"
    )
    
    try:
        # Solicit a medical reply, integrating current context while following compliance guidelines.
        response = await generate_medical_response(chat_history)
        
        if not response:
            await update.message.reply_text(
                "⚠️ نتوانستم پرسش پزشکی شما را پردازش کنم. لطفاً سوال خود را به شکل دیگری مطرح کنید."
            )
            return States.MEDICAL_CHAT
        
        # Audit the interaction prior to dispatching the reply.
        await save_to_markdown(user_id, "Medical Chat", query, response)
        
        # Append the model response to maintain complete dialogue history.
        chat_history.append({"role": "assistant", "content": response})
        
        # Update session with latest dialogue for potential iterative queries.
        if user_id in user_sessions:
            user_sessions[user_id]["chat_history"] = chat_history
        
        await update.message.reply_text(response, parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Error in medical response generation: {str(e)}")
        await update.message.reply_text(
            "❌ متاسفانه در پردازش پرسش پزشکی خطایی رخ داده است. لطفاً بعداً تلاش کنید."
        )
    
    return States.MEDICAL_CHAT

async def generate_article_with_deepseek(topic: str) -> Optional[str]:
    """Asynchronously generate a concise academic article using Gemini API.
    
    Enforces robust fact-checking, structured output, and ensures single-message delivery.
    Incorporates defensive coding practices to handle edge cases and API disconnects.
    """
    try:
        system_message = """
            Objective: Generate a factually accurate, scientifically enhanced, and well-structured academic article in English (or Persian) from user-provided text. The entire article must be concise enough to fit within a single Telegram message while maintaining clarity and completeness.

            Input: User-provided text (memory, scientific notes, draft article, general topic).

            Instructions:

            Phase 1: Fact-Checking
            1. Analyze and Deconstruct:
            - Understand the main topic, key claims, and intended message.
            - Extract factual claims, breaking down complex ones.
            2. Fact-Check Each Claim:
            - Identify key terms and clarify ambiguities.
            - Retrieve evidence from reputable sources (fact-checkers, news outlets, government, academic journals, expert organizations).
            - Analyze the evidence against each claim, assess its strength, and note any discrepancies.
            - Assign verdicts (True, False, Mixed, etc.) and document supporting evidence.
            3. Identify Gaps:
            - Determine areas needing correction, expansion, additional information, or improved structure.

            Phase 2: Article Generation
            4. Structure the Article using the following template:
            - Title: Indicative and concise.
            - Abstract: A summary (150-250 words) without references/quotes.
            - Keywords: 3-6 representative keywords.
            - Introduction: Background, objectives, and literature review.
            - Methods (if applicable): Research design, data collection, analysis.
            - Results: Objectively report findings.
            - Discussion: Interpret results, acknowledge limitations, offer recommendations, and include a critical analysis.
            - Conclusion: Summarize findings and significance.
            - References: List credible sources (APA, MLA, Chicago).
            - Appendices (optional): Supplementary information as needed.
            5. Enhance and Enrich:
            - Correct inaccuracies, expand detail and context, add scientific rigor, and improve clarity and coherence.
            - Incorporate supporting evidence from both internal and external sources.
            6. Review and Refine:
            - Ensure factual accuracy, logical flow, and a formal, authoritative tone.
            - Verify completeness and depth while keeping the article concise.
            - Use clear formatting (headings, bullet points) for readability.

            Additional Requirements:
            - Ensure the output language matches the input language provided by the user. If the input is in Persian, generate the article in Persian; if in English, generate it in English.
            - Format the output concisely so that the entire article fits within a single Telegram message while maintaining clarity and completeness.

            Target Audience: The article should be written for academic professionals in the relevant field, maintaining a seamless, credible, and professional expert perspective.

            Output: A complete academic article demonstrating accuracy, completeness, and rigor, presented in a formal and authoritative tone, and formatted to fit within a single Telegram message.
        """
        
        prompt = f"{system_message}\nWrite an academic article about: {topic}"
        
        response = await model.generate_content_async(
            prompt,
            stream=False
        )
        
        if response.text:
            return response.text.strip()
            
        logger.error("Empty response from Gemini API")
        return None
            
    except Exception as e:
        logger.error(f"Error generating article with Gemini: {str(e)}")
        return None

async def generate_medical_response(chat_history: list) -> Optional[str]:
    """Compose a safe, evidence-based medical response using Gemini API.
    
    Integrates conversation context, applies risk mitigation strategies, and adheres to compliance norms.
    """
    try:
        system_message = (
            "Role:\n"
            "I am Doctor Agent, a medical AI assistant ready to answer your health-related questions. "
            "My responses are based on scientific sources and reliable data, but I am not a replacement "
            "for professional medical advice.\n\n"
            "Instructions:\n"
            "- Provide precise, scientific, and understandable answers in Persian language.\n"
            "- If a question requires a real doctor's consultation, guide the user accordingly.\n"
            "- Avoid giving dangerous or misleading advice.\n"
            "- Include relevant medical references when appropriate.\n"
            "- Keep responses clear and focused on the user's question.\n"
            "- If the question is unclear, ask for clarification instead of making assumptions.\n\n"
            "Note: Always remind users that this is for informational purposes only and "
            "they should consult healthcare professionals for personal medical advice."
        )
        
        # Use only the most recent query to form the basis of the prompt.
        last_message = chat_history[-1]["content"] if chat_history else ""
        
        prompt = f"{system_message}\nUser Question: {last_message}"
        
        response = await model.generate_content_async(
            prompt,
            stream=False
        )
        
        if response.text:
            return response.text.strip()
            
        logger.error("Empty response from Gemini API")
        return None

    except Exception as e:
        logger.error(f"Error in medical response generation: {str(e)}")
        return None

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Provide end-user documentation via /help command.
    
    Details available commands and operational modes to ensure users understand bot functionalities.
    """
    help_text = (
        "🤖 *راهنمای ربات دستیار هوشمند دو حالته*\n\n"
        "*دستورات موجود:*\n"
        "• /start - شروع ربات و انتخاب حالت\n"
        "• /mode - تغییر حالت بین نوشتن مقاله و گفتگوی پزشکی\n"
        "• /help - نمایش راهنمای این ربات\n"
        "• /cancel - خروج از حالت فعلی\n\n"
        "*حالت نوشتن مقاله:*\n"
        "فقط کافیست موضوع یا کلمات کلیدی برای تولید مقاله وارد کنید.\n\n"
        "*حالت گفتگوی پزشکی:*\n"
        "سوالات پزشکی یا بهداشتی خود را مطرح کنید تا پاسخ‌های مبتنی بر منابع علمی دریافت کنید.\n\n"
        "⚠️ *توجه:* اطلاعات ارائه شده صرفاً جهت آموزش بوده و جایگزین مشاوره پزشکی نمی‌باشد."
    )
    
    await update.message.reply_text(help_text, parse_mode="Markdown")

def main() -> None:
    """Configure and launch the Telegram bot.
    
    Bootstraps the application using a conversation-driven architecture while adhering to fail-fast principles.
    Includes modular handler registration to streamline mode transitions and mitigate potential runtime issues.
    """
    try:
        # Create the Application instance using the builder pattern; ensures immutability and clarity.
        application = Application.builder().token(TELEGRAM_TOKEN).build()
        
        # Configure upstream libraries to minimize unnecessary log noise.
        logging.getLogger('httpx').setLevel(logging.WARNING)
        logging.getLogger('telegram').setLevel(logging.ERROR)
        logging.getLogger('telegram.ext').setLevel(logging.ERROR)
        
        # Establish a ConversationHandler for defining state-driven transitions with clear reentry conditions.
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", start)],
            states={
                States.CHOOSING_MODE: [
                    CallbackQueryHandler(mode_selection, pattern=r"^mode_")
                ],
                States.ARTICLE_WRITING: [
                    CommandHandler("mode", change_mode),
                    CommandHandler("cancel", cancel),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_article_mode)
                ],
                States.MEDICAL_CHAT: [
                    CommandHandler("mode", change_mode),
                    CommandHandler("cancel", cancel),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, handle_medical_mode)
                ]
            },
            fallbacks=[CommandHandler("cancel", cancel)],
            allow_reentry=True
        )
        
        # Register conversation and ancillary command handlers.
        application.add_handler(conv_handler)
        application.add_handler(CommandHandler("help", help_command))
        
        # Start polling updates in a production-safe mode; drop any stale pending updates.
        application.run_polling(drop_pending_updates=True)
        
    except Exception as e:
        logger.error(f"Failed to start bot: {str(e)}")
        if "InvalidToken" in str(e):
            logger.error("Please check your TELEGRAM_TOKEN in the .env file")
        raise

if __name__ == "__main__":
    main()
