import os
import requests
import uuid
import json
from telebot.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# The URL where your Flask backend is running (port 3005 as configured in Nginx/app)
BACKEND_URL = "http://127.0.0.1:3005"

# In-memory store for user state
# { chat_id: {'latex_code': str, 'teacher_name': str, 'layout': str, 'topic': str} }
USER_DATA = {}

def register_handlers(bot):
    
    @bot.message_handler(commands=['start', 'help'])
    def send_welcome(message: Message):
        markup = InlineKeyboardMarkup()
        btn_help = InlineKeyboardButton("📖 Как это работает?", callback_data='help_info')
        markup.add(btn_help)
        
        bot.reply_to(message, 
            "Привет! 👋 Я бот *Worksheet Creator*.\n\n"
            "Я умею превращать фотографии с математическими заданиями в красивые рабочие листы в формате PDF (вместе с ответами!).\n\n"
            "Просто отправьте мне фото заданий, и я сделаю всю магию ✨",
            parse_mode="Markdown",
            reply_markup=markup
        )

    @bot.callback_query_handler(func=lambda call: call.data == 'help_info')
    def help_callback(call: CallbackQuery):
        instructions = (
            "📌 *Инструкция по использованию:*\n\n"
            "1. Сфотографируйте страницу учебника или задания (старайтесь делать фото четко).\n"
            "2. Отправьте это фото мне.\n"
            "3. Немного подождите ⏳ (я распознаю текст, переведу его в LaTeX и сгенерирую PDF-файлы).\n"
            "4. В ответ вы получите два документа:\n"
            "   📄 `worksheet.pdf` - готовый красивый рабочий лист для распечатки.\n"
            "   🔑 `keys.pdf` - список ответов на все задачи для быстрой проверки.\n\n"
            "💡 _Готовы? Просто пришлите мне первую картинку!_"
        )
        bot.answer_callback_query(call.id)
        bot.send_message(call.message.chat.id, instructions, parse_mode="Markdown")

    @bot.message_handler(content_types=['photo'])
    def handle_photo(message: Message):
        bot.send_message(message.chat.id, "🤖 Принял фото. Отправляю на распознавание серверу Worksheet Creator...")
        
        try:
            # Get the highest resolution photo
            file_info = bot.get_file(message.photo[-1].file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            
            # Save temporarily
            tmp_filename = f"tmp_{uuid.uuid4()}.jpg"
            tmp_filepath = os.path.join(os.path.dirname(__file__), tmp_filename)
            
            with open(tmp_filepath, 'wb') as new_file:
                new_file.write(downloaded_file)
            
            bot.send_message(message.chat.id, "⏳ Распознаю текст и генерирую LaTeX код...")
            
            # Send to backend
            with open(tmp_filepath, 'rb') as f:
                files = {'files': (tmp_filename, f, 'image/jpeg')}
                teacher = '@' + str(message.from_user.username) if message.from_user.username else ''
                data = {'topic': 'Рабочий лист (из Telegram)', 'teacher_name': teacher}
                
                resp = requests.post(f"{BACKEND_URL}/api/process", files=files, data=data)
            
            # Clean up temp file
            if os.path.exists(tmp_filepath):
                os.remove(tmp_filepath)
                
            if resp.status_code == 200:
                resp_data = resp.json()
                latex_code = resp_data.get('latex_code')
                
                if latex_code:
                    USER_DATA[message.chat.id] = {
                        'latex_code': latex_code,
                        'teacher_name': teacher,
                        'topic': 'Рабочий лист (из Telegram)',
                        'layout': '1col'
                    }
                    
                    markup = InlineKeyboardMarkup(row_width=2)
                    btn1 = InlineKeyboardButton("📝 1 колонка", callback_data='compile_1col')
                    btn2 = InlineKeyboardButton("📰 2 колонки", callback_data='compile_2col')
                    markup.add(btn1, btn2)
                    
                    bot.send_message(message.chat.id, "✅ Текст распознан! Выберите формат макета:", reply_markup=markup)
                else:
                    bot.send_message(message.chat.id, "❌ Не удалось получить LaTeX код от сервера.")
            else:
                err = resp.text[:500] + "..." if len(resp.text) > 500 else resp.text
                bot.send_message(message.chat.id, f"❌ Ошибка сервера при распознавании: {err}")
                
        except Exception as e:
            err = str(e)[:500] + "..." if len(str(e)) > 500 else str(e)
            bot.reply_to(message, f"❌ Произошла ошибка: {err}")

    def call_compile_and_send(chat_id, latex_code, topic, teacher_name, layout, is_variant2=False):
        bot.send_message(chat_id, "⏳ Компилирую PDF...")
        try:
            compile_resp = requests.post(f"{BACKEND_URL}/api/compile", json={
                'latex_code': latex_code,
                'topic': topic,
                'teacher_name': teacher_name,
                'is_variant2': is_variant2,
                'layout': layout
            })
            
            if compile_resp.status_code == 200:
                compile_data = compile_resp.json()
                pdf_url = compile_data.get('pdf_url')
                keys_url = compile_data.get('keys_url')
                
                # Fetch PDFs and send
                if pdf_url:
                    pdf_url_local = pdf_url.replace('/worksheet-api/', '/api/')
                    pdf_resp = requests.get(f"{BACKEND_URL}{pdf_url_local}")
                    if pdf_resp.status_code == 200:
                        doc_name = "variant2.pdf" if is_variant2 else "worksheet.pdf"
                        bot.send_document(chat_id, (doc_name, pdf_resp.content))
                        
                if keys_url:
                    keys_url_local = keys_url.replace('/worksheet-api/', '/api/')
                    keys_resp = requests.get(f"{BACKEND_URL}{keys_url_local}")
                    if keys_resp.status_code == 200:
                        doc_name = "variant2_keys.pdf" if is_variant2 else "keys.pdf"
                        bot.send_document(chat_id, (doc_name, keys_resp.content))
                        
                bot.send_message(chat_id, "🎉 Готово! Ваш рабочий лист успешно создан.")
                
                if not is_variant2:
                    # Offer to create Variant 2
                    markup = InlineKeyboardMarkup(row_width=1)
                    btn1 = InlineKeyboardButton("🔽 Генерировать (Проще)", callback_data='var2_easier')
                    btn2 = InlineKeyboardButton("🔄 Генерировать (Так же)", callback_data='var2_same')
                    btn3 = InlineKeyboardButton("🔼 Генерировать (Сложнее)", callback_data='var2_harder')
                    markup.add(btn1, btn2, btn3)
                    bot.send_message(chat_id, "Хотите создать **Вариант 2** на основе этих заданий?", reply_markup=markup, parse_mode="Markdown")
            else:
                err = compile_resp.text[:500] + "..." if len(compile_resp.text) > 500 else compile_resp.text
                bot.send_message(chat_id, f"❌ Ошибка компиляции PDF: {err}")
        except Exception as e:
            err = str(e)[:500] + "..." if len(str(e)) > 500 else str(e)
            bot.send_message(chat_id, f"❌ Произошла ошибка компиляции: {err}")

    @bot.callback_query_handler(func=lambda call: call.data.startswith('compile_'))
    def compile_callback(call: CallbackQuery):
        chat_id = call.message.chat.id
        layout = '1col' if call.data == 'compile_1col' else '2col'
        
        user_info = USER_DATA.get(chat_id)
        if not user_info:
            bot.answer_callback_query(call.id, "Данные устарели. Пожалуйста, отправьте фото снова.")
            return
            
        bot.answer_callback_query(call.id)
        bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
        
        user_info['layout'] = layout
        call_compile_and_send(
            chat_id, 
            user_info['latex_code'], 
            user_info['topic'], 
            user_info['teacher_name'], 
            layout, 
            is_variant2=False
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith('var2_'))
    def var2_callback(call: CallbackQuery):
        chat_id = call.message.chat.id
        difficulty = call.data.split('_')[1] # easier, same, harder
        
        user_info = USER_DATA.get(chat_id)
        if not user_info:
            bot.answer_callback_query(call.id, "Данные устарели. Пожалуйста, отправьте оригинальное фото снова.")
            return
            
        bot.answer_callback_query(call.id)
        bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
        
        bot.send_message(chat_id, "🤖 Генерирую Вариант 2 (ИИ придумывает новые задачи)... Это может занять около минуты.")
        
        try:
            resp = requests.post(f"{BACKEND_URL}/api/generate_similar", data={
                'original_text': user_info['latex_code'],
                'task_count': 3,
                'difficulty': difficulty,
                'topic': user_info['topic'],
                'teacher_name': user_info['teacher_name']
            })
            
            if resp.status_code == 200:
                resp_data = resp.json()
                new_latex_code = resp_data.get('latex_code')
                
                if new_latex_code:
                    call_compile_and_send(
                        chat_id, 
                        new_latex_code, 
                        user_info['topic'], 
                        user_info['teacher_name'], 
                        user_info['layout'], 
                        is_variant2=True
                    )
                else:
                    bot.send_message(chat_id, "❌ Не удалось получить код Варианта 2 от сервера.")
            else:
                err = resp.text[:500] + "..." if len(resp.text) > 500 else resp.text
                bot.send_message(chat_id, f"❌ Ошибка генерации Варианта 2: {err}")
        except Exception as e:
            err = str(e)[:500] + "..." if len(str(e)) > 500 else str(e)
            bot.send_message(chat_id, f"❌ Произошла ошибка сети: {err}")
