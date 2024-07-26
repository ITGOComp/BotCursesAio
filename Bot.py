import aiogram
from sqlalchemy.orm import declarative_base
from aiogram import Bot, Dispatcher, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, InputFile
from aiogram.utils import executor
import logging
from Tokens import TOKEN
from sqlalchemy import create_engine, Column, String, Text, Integer, Sequence
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import declarative_base, sessionmaker

logging.basicConfig(level=logging.INFO)

# Переменные для хранения состояния
admin_data = {}
message_ids = {}  # Словарь для хранения идентификаторов сообщений
message_ids['start_message'] = None  # Новый элемент для хранения ID сообщения с кнопкой "Посмотреть курсы"
search_state = {}  # Для отслеживания состояния поиска курсов

# Настройка баз данных
DATABASE_URL_BOT = "sqlite:///courses_bot.db"
DATABASE_URL_YOUTUBE = "sqlite:///courses_youtube.db"

engine_bot = create_engine(DATABASE_URL_BOT)
engine_youtube = create_engine(DATABASE_URL_YOUTUBE)

Base = declarative_base()

SessionLocalBot = sessionmaker(autocommit=False, autoflush=False, bind=engine_bot)
SessionLocalYoutube = sessionmaker(autocommit=False, autoflush=False, bind=engine_youtube)

class AdminUser(Base):
    __tablename__ = "admin_users"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, unique=True)
    role = Column(String)  # Роль админа: 'bot' или 'youtube'

class Course(Base):
    __tablename__ = "courses"
    id = Column(Integer, Sequence('course_id_seq'), primary_key=True, index=True)
    title = Column(String, index=True)
    description = Column(Text)
    link = Column(String)
    videos = Column(Text)
    added_by = Column(String)
    avatar = Column(String)  # Поле для хранения пути к аватарке

class Assignment(Base):
    __tablename__ = "assignments"
    id = Column(Integer, Sequence('assignment_id_seq'), primary_key=True, index=True)
    course_id = Column(Integer, index=True)
    title = Column(String)
    description = Column(Text)
    task = Column(Text)
    answer = Column(Text)

Base.metadata.create_all(bind=engine_bot)
Base.metadata.create_all(bind=engine_youtube)

bot = Bot(token=TOKEN)
dp = Dispatcher(bot)

# Переменная для хранения текущей страницы и источника курсов
current_pages = {}

# Команда /start
@dp.message_handler(commands=['start'])
async def send_welcome(message: types.Message):
    keyboard = InlineKeyboardMarkup()
    button = InlineKeyboardButton(text="Посмотреть курсы", callback_data="view_courses")
    keyboard.add(button)
    sent_message = await message.reply("Привет, этот бот поможет тебе с изучением разных языков программирования и не только.", reply_markup=keyboard)
    message_ids['start_message'] = sent_message.message_id

# Обработка нажатия на кнопку "Посмотреть курсы"
@dp.callback_query_handler(lambda c: c.data == 'view_courses')
async def process_view_courses(callback_query: types.CallbackQuery):
    if message_ids.get('start_message'):
        await bot.delete_message(callback_query.from_user.id, message_ids['start_message'])
        del message_ids['start_message']
    
    keyboard = InlineKeyboardMarkup()
    button1 = InlineKeyboardButton(text="С данных бота", callback_data="from_bot")
    button2 = InlineKeyboardButton(text="С YouTube", callback_data="from_youtube")
    keyboard.add(button1, button2)
    
    sent_message = await bot.send_message(callback_query.from_user.id, "Выберите откуда вы хотите брать знания", reply_markup=keyboard)
    message_ids['view_courses'] = sent_message.message_id

# Обработка выбора источника знаний
@dp.callback_query_handler(lambda c: c.data in ['from_bot', 'from_youtube'])
async def process_source(callback_query: types.CallbackQuery):
    source = callback_query.data.split('_')[1]
    current_pages[callback_query.from_user.id] = {'source': source, 'page': 0}
    await send_courses_list(callback_query.from_user.id, source, 0)

@dp.callback_query_handler(lambda c: c.data == 'find_by_id')
async def process_find_by(callback_query: types.CallbackQuery):
    # Устанавливаем состояние поиска
    search_state[callback_query.from_user.id] = {'state': callback_query.data}

    # Определяем текст сообщения для запроса
    prompt = "Пожалуйста, введите ID курса."
    
    # Отправляем запрос на ввод ID или заголовка и сохраняем ID этого сообщения
    sent_message = await bot.send_message(callback_query.from_user.id, prompt)
    search_state[callback_query.from_user.id]['request_message_id'] = sent_message.message_id

async def send_courses_list(user_id, source, page):
    session = SessionLocalBot() if source == 'bot' else SessionLocalYoutube()
    courses = session.query(Course).offset(page * 10).limit(10).all()
    session.close()
    
    message_text = "Вот список доступных курсов:\n\n"
    for course in courses:
        message_text += f"ID: {course.id}, Название: {course.title}\n"
    
    keyboard = InlineKeyboardMarkup()
    navigation_buttons = []
    if page > 0:
        navigation_buttons.append(InlineKeyboardButton(text="Назад", callback_data=f"prev_page_{page - 1}"))
    if len(courses) == 10:
        navigation_buttons.append(InlineKeyboardButton(text="Далее", callback_data=f"next_page_{page + 1}"))
    
    navigation_buttons.append(InlineKeyboardButton(text="Найти по ID", callback_data="find_by_id"))
    
    if navigation_buttons:
        keyboard.add(*navigation_buttons)
    
    if 'source_courses' in message_ids:
        try:
            await bot.delete_message(user_id, message_ids['source_courses'])
        except aiogram.utils.exceptions.MessageToDeleteNotFound:
            logging.warning("Attempted to delete a message that was not found")
        del message_ids['source_courses']
    
    sent_message = await bot.send_message(user_id, message_text, reply_markup=keyboard)
    message_ids['source_courses'] = sent_message.message_id

@dp.callback_query_handler(lambda c: c.data.startswith('prev_page_') or c.data.startswith('next_page_'))
async def process_pagination(callback_query: types.CallbackQuery):
    data = callback_query.data.split('_')
    action = data[0]
    page = int(data[2])
    source = current_pages[callback_query.from_user.id]['source']
    
    await send_courses_list(callback_query.from_user.id, source, page)

@dp.callback_query_handler(lambda c: c.data == 'find_by_id')
async def process_find_by(callback_query: types.CallbackQuery):
    search_state[callback_query.from_user.id] = {'state': callback_query.data}
    prompt = "Пожалуйста, введите ID курса."
    await bot.send_message(callback_query.from_user.id, prompt)

@dp.message_handler(lambda message: message.from_user.id in search_state and search_state[message.from_user.id]['state'] in ['find_by_id', 'find_by_title'])
async def process_search(message: types.Message):
    user_id = message.from_user.id
    state = search_state[user_id]['state']
    
    session = SessionLocalBot() if current_pages[user_id]['source'] == 'bot' else SessionLocalYoutube()
    
    # Удаление сообщения с запросом
    @dp.message_handler(lambda message: message.from_user.id in search_state and search_state[message.from_user.id]['state'] in ['find_by_id', 'find_by_title'])
    async def process_search(message: types.Message):
        user_id = message.from_user.id
        state = search_state[user_id]['state']
        
        session = SessionLocalBot() if current_pages[user_id]['source'] == 'bot' else SessionLocalYoutube()
        
        if 'request_message_id' in search_state[user_id]:
            try:
                await bot.delete_message(user_id, search_state[user_id]['request_message_id'])
            except Exception as e:
                print(f"Не удалось удалить сообщение: {e}")
            del search_state[user_id]['request_message_id']
        
        if state == 'find_by_id':
            try:
                course_id = int(message.text)
                course = session.query(Course).filter(Course.id == course_id).first()
                if course:
                    course_details = (
                        f"*{course.title}*\n\n"
                        f"Описание: {course.description}\n\n"
                        f"Добавил: {course.added_by}"
                    )
                    keyboard = InlineKeyboardMarkup()
                    link_button = InlineKeyboardButton(text="Перейти к курсу", url=course.link)
                    keyboard.add(link_button)
                    
                    assignment_button = InlineKeyboardButton(text="Домашнее задание", callback_data=f"view_assignments_{course.id}")
                    keyboard.add(assignment_button)
                    
                    if course.avatar:
                        if course.avatar.startswith('http'):
                            await bot.send_photo(user_id, photo=course.avatar, caption=course_details, reply_markup=keyboard, parse_mode='Markdown')
                        else:
                            await bot.send_photo(user_id, photo=InputFile(course.avatar), caption=course_details, reply_markup=keyboard, parse_mode='Markdown')
                    else:
                        await bot.send_message(user_id, course_details, reply_markup=keyboard, parse_mode='Markdown')
                else:
                    await bot.send_message(user_id, "Такого курса нет.")
            except ValueError:
                await bot.send_message(user_id, "Пожалуйста, введите корректный ID курса.")
        
        session.close()
        search_state[user_id]['state'] = 'none'






@dp.callback_query_handler(lambda c: c.data.startswith('view_assignments_'))
async def process_view_assignments(callback_query: types.CallbackQuery):
    course_id = int(callback_query.data.split('_')[2])
    session = SessionLocalBot()
    assignments = session.query(Assignment).filter(Assignment.course_id == course_id).all()
    session.close()
    
    if assignments:
        message_text = "Вот список домашних заданий:\n\n"
        keyboard = InlineKeyboardMarkup()
        for assignment in assignments:
            message_text += f"ID: {assignment.id}, Название: {assignment.title}\n"
            keyboard.add(InlineKeyboardButton(text=f"Открыть задание {assignment.id}", callback_data=f"open_assignment_{assignment.id}"))
        
        await bot.send_message(callback_query.from_user.id, message_text, reply_markup=keyboard)
    else:
        await bot.send_message(callback_query.from_user.id, "У этого курса нет домашних заданий.")

@dp.callback_query_handler(lambda c: c.data.startswith('open_assignment_'))
async def process_open_assignment(callback_query: types.CallbackQuery):
    assignment_id = int(callback_query.data.split('_')[2])
    session = SessionLocalBot()
    assignment = session.query(Assignment).filter(Assignment.id == assignment_id).first()
    session.close()
    
    if assignment:
        assignment_details = (
            f"*{assignment.title}*\n\n"
            f"Описание: {assignment.description}\n\n"
            f"Задание: {assignment.task}\n\n"
            f"Ответ: {assignment.answer}"
        )
        await bot.send_message(callback_query.from_user.id, assignment_details, parse_mode='Markdown')
    else:
        await bot.send_message(callback_query.from_user.id, "Такого задания нет.")

# Обработка команды /admin
@dp.message_handler(commands=['admin'])
async def admin_panel(message: types.Message):
    user_id = message.from_user.id

    # Проверяем, является ли пользователь администратором по фиксированному ID
    if user_id == 847721655:  # Убедитесь, что это правильный ID
        is_admin = True
    else:
        # Проверка на наличие пользователя в базе данных
        session_bot = SessionLocalBot()
        session_youtube = SessionLocalYoutube()
        
        is_bot_admin = session_bot.query(AdminUser).filter(AdminUser.user_id == user_id).first() is not None
        is_youtube_admin = session_youtube.query(AdminUser).filter(AdminUser.user_id == user_id).first() is not None
        
        logging.info(f"User ID: {user_id}")
        logging.info(f"Is Bot Admin: {is_bot_admin}")
        logging.info(f"Is YouTube Admin: {is_youtube_admin}")
        
        session_bot.close()
        session_youtube.close()
        
        is_admin = is_bot_admin or is_youtube_admin

    if not is_admin:
        await message.reply("У вас нет доступа к админ панели.")
        return

    if user_id not in admin_data:
        admin_data[user_id] = {'step': 0, 'course': {}, 'db': None}

    keyboard = InlineKeyboardMarkup()
    button1 = InlineKeyboardButton(text="На YouTube", callback_data="upload_youtube")
    button2 = InlineKeyboardButton(text="В бота", callback_data="upload_bot")
    
    if user_id == 847721655:
        button3 = InlineKeyboardButton(text="Добавить пользователя", callback_data="add_user")
        keyboard.add(button3)
    
    keyboard.add(button1, button2)
    
    await message.reply("Выберите действие:", reply_markup=keyboard)


@dp.callback_query_handler(lambda c: c.data == 'add_user')
async def process_add_user(callback_query: types.CallbackQuery):
    if callback_query.from_user.id != 847721655:
        await bot.send_message(callback_query.from_user.id, "У вас нет доступа к этой функции.")
        return
    
    keyboard = InlineKeyboardMarkup()
    button_youtube = InlineKeyboardButton(text="YouTube", callback_data="add_youtube_admin")
    button_bot = InlineKeyboardButton(text="Бот", callback_data="add_bot_admin")
    keyboard.add(button_youtube, button_bot)
    
    await bot.send_message(callback_query.from_user.id, "Какого админа вы хотите добавить?", reply_markup=keyboard)

@dp.callback_query_handler(lambda c: c.data in ['add_youtube_admin', 'add_bot_admin'])
async def process_add_admin(callback_query: types.CallbackQuery):
    role = 'youtube' if callback_query.data == 'add_youtube_admin' else 'bot'
    admin_data[callback_query.from_user.id] = {'step': 5, 'role': role}
    await bot.send_message(callback_query.from_user.id, "Отправьте ID пользователя, которого вы хотите добавить.")

@dp.message_handler(lambda message: message.from_user.id in admin_data and admin_data[message.from_user.id]['step'] == 5)
async def process_admin_id(message: types.Message):
    user_id = message.from_user.id
    data = admin_data[user_id]
    
    try:
        new_user_id = int(message.text)
        role = data['role']
        
        session = SessionLocalBot() if role == 'bot' else SessionLocalYoutube()
        if not session.query(AdminUser).filter(AdminUser.user_id == new_user_id).first():
            new_user = AdminUser(user_id=new_user_id, role=role)
            session.add(new_user)
            session.commit()
            await message.reply("Пользователь успешно добавлен.")
        else:
            await message.reply("Этот пользователь уже есть в базе данных.")
        session.close()
        
        del admin_data[user_id]
    except ValueError:
        await message.reply("Пожалуйста, отправьте корректный ID пользователя.")

@dp.callback_query_handler(lambda c: c.data == 'upload_bot')
async def process_upload_bot(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    # Проверяем, что у пользователя есть роль 'bot'
    session = SessionLocalBot()
    admin = session.query(AdminUser).filter(AdminUser.user_id == user_id).first()
    session.close()
    
    if admin and admin.role == 'bot':
        admin_data[user_id]['db'] = 'bot'
        admin_data[user_id]['step'] = 0
        await bot.send_message(user_id, "Начинаем добавление нового курса в бота. Пожалуйста, отправьте название курса.")
    else:
        await bot.send_message(user_id, "У вас нет доступа к этой функции.")

@dp.callback_query_handler(lambda c: c.data == 'upload_youtube')
async def process_upload_youtube(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    # Проверяем, что у пользователя есть роль 'youtube'
    session = SessionLocalYoutube()
    admin = session.query(AdminUser).filter(AdminUser.user_id == user_id).first()
    session.close()
    
    if admin and admin.role == 'youtube':
        if user_id not in admin_data:
            admin_data[user_id] = {'step': 0, 'course': {}, 'db': 'youtube'}
        else:
            admin_data[user_id]['db'] = 'youtube'
        admin_data[user_id]['step'] = 0
        await bot.send_message(user_id, "Начинаем добавление нового курса на YouTube. Пожалуйста, отправьте название курса.")
    else:
        await bot.send_message(user_id, "У вас нет доступа к этой функции.")
    
@dp.message_handler(lambda message: message.from_user.id in admin_data)
async def process_admin_message(message: types.Message):
    user_id = message.from_user.id
    data = admin_data[user_id]
    
    if data['step'] == 0:
        data['course']['title'] = message.text
        data['step'] = 1
        await message.reply("Теперь отправьте описание курса.")
    
    elif data['step'] == 1:
        data['course']['description'] = message.text
        data['step'] = 2
        await message.reply("Отправьте ссылку на курс.")
    
    elif data['step'] == 2:
        data['course']['link'] = message.text
        data['step'] = 3
        await message.reply("Теперь отправьте аватарку курса. Это может быть изображение, сохраненное на сервере или URL к изображению.")
    
    elif data['step'] == 3:
        if message.photo:
            file_id = message.photo[-1].file_id
            file_info = await bot.get_file(file_id)
            file_path = file_info.file_path
            data['course']['avatar'] = file_path
        else:
            data['course']['avatar'] = message.text
        
        data['step'] = 4
        await message.reply("Укажите ваше имя.")
    
    elif data['step'] == 4:
        data['course']['added_by'] = message.text
        
        # Добавление курса в базу данных
        if data['db'] == 'bot':
            session = SessionLocalBot()
        else:
            session = SessionLocalYoutube()
        
        new_course = Course(
            title=data['course']['title'],
            description=data['course']['description'],
            link=data['course']['link'],
            added_by=data['course']['added_by'],
            avatar=data['course']['avatar']
        )
        session.add(new_course)
        session.commit()
        session.close()
        
        # Предложение добавить домашние задания
        keyboard = InlineKeyboardMarkup()
        button_yes = InlineKeyboardButton(text="Да", callback_data="add_homework_yes")
        button_no = InlineKeyboardButton(text="Нет", callback_data="add_homework_no")
        keyboard.add(button_yes, button_no)
        
        await message.reply("Курс успешно добавлен. Добавить домашнее задание?", reply_markup=keyboard)
        del admin_data[user_id]

@dp.callback_query_handler(lambda c: c.data == 'add_homework_yes')
async def process_add_homework(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    admin_data[user_id] = {'step': 10}
    await bot.send_message(user_id, "Введите ID курса для добавления домашнего задания.")

@dp.callback_query_handler(lambda c: c.data == 'add_homework_no')
async def process_no_homework(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    await bot.send_message(user_id, "Домашние задания не были добавлены.")
    del admin_data[user_id]

@dp.message_handler(lambda message: message.from_user.id in admin_data and admin_data[message.from_user.id]['step'] == 10)
async def process_course_id_for_homework(message: types.Message):
    user_id = message.from_user.id
    try:
        course_id = int(message.text)
        session = SessionLocalBot()  # Используйте соответствующую базу данных
        course = session.query(Course).filter(Course.id == course_id).first()
        session.close()
        
        if course:
            admin_data[user_id]['course_id'] = course_id
            admin_data[user_id]['step'] = 11
            await bot.send_message(user_id, "Теперь отправьте количество домашних заданий.")
        else:
            await bot.send_message(user_id, "Курс с таким ID не найден.")
    except ValueError:
        await bot.send_message(user_id, "Пожалуйста, введите корректный ID курса.")

@dp.message_handler(lambda message: message.from_user.id in admin_data and admin_data[message.from_user.id]['step'] == 11)
async def process_homework_count(message: types.Message):
    user_id = message.from_user.id
    try:
        count = int(message.text)
        if count > 0:
            admin_data[user_id]['homework_count'] = count
            admin_data[user_id]['current_homework'] = 0
            admin_data[user_id]['step'] = 12
            await bot.send_message(user_id, "Теперь отправьте название домашнего задания.")
        else:
            await bot.send_message(user_id, "Количество домашних заданий должно быть положительным числом.")
    except ValueError:
        await bot.send_message(user_id, "Пожалуйста, введите корректное количество домашних заданий.")

@dp.message_handler(lambda message: message.from_user.id in admin_data)
async def process_admin_message(message: types.Message):
    user_id = message.from_user.id
    data = admin_data[user_id]
    
    # Инициализация данных, если они отсутствуют
    if 'course' not in data:
        data['course'] = {}

    if data['step'] == 0:
        data['course']['title'] = message.text
        data['step'] = 1
        await message.reply("Теперь отправьте описание курса.")
    
    elif data['step'] == 1:
        data['course']['description'] = message.text
        data['step'] = 2
        await message.reply("Отправьте ссылку на курс.")
    
    elif data['step'] == 2:
        data['course']['link'] = message.text
        data['step'] = 3
        await message.reply("Теперь отправьте аватарку курса. Это может быть изображение, сохраненное на сервере или URL к изображению.")
    
    elif data['step'] == 3:
        if message.photo:
            file_id = message.photo[-1].file_id
            file_info = await bot.get_file(file_id)
            file_path = file_info.file_path
            data['course']['avatar'] = file_path
        else:
            data['course']['avatar'] = message.text
        
        data['step'] = 4
        await message.reply("Укажите ваше имя.")
    
    elif data['step'] == 4:
        data['course']['added_by'] = message.text
        
        # Добавление курса в базу данных
        if data['db'] == 'bot':
            session = SessionLocalBot()
        else:
            session = SessionLocalYoutube()
        
        new_course = Course(
            title=data['course']['title'],
            description=data['course']['description'],
            link=data['course']['link'],
            added_by=data['course']['added_by'],
            avatar=data['course']['avatar']
        )
        session.add(new_course)
        session.commit()
        session.close()
        
        # Предложение добавить домашние задания
        keyboard = InlineKeyboardMarkup()
        button_yes = InlineKeyboardButton(text="Да", callback_data="add_homework_yes")
        button_no = InlineKeyboardButton(text="Нет", callback_data="add_homework_no")
        keyboard.add(button_yes, button_no)
        
        await message.reply("Курс успешно добавлен. Добавить домашнее задание?", reply_markup=keyboard)
        del admin_data[user_id]





@dp.callback_query_handler(lambda c: c.data == 'add_homework_yes')
async def process_add_homework(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    admin_data[user_id] = {'step': 10}  # Начинаем процесс добавления домашнего задания
    await bot.send_message(user_id, "Введите ID курса для добавления домашнего задания.")

@dp.callback_query_handler(lambda c: c.data == 'add_homework_no')
async def process_no_homework(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    await bot.send_message(user_id, "Домашние задания не были добавлены.")
    del admin_data[user_id]

@dp.message_handler(lambda message: message.from_user.id in admin_data and admin_data[message.from_user.id]['step'] == 10)
async def process_course_id_for_homework(message: types.Message):
    user_id = message.from_user.id
    try:
        course_id = int(message.text)
        session = SessionLocalBot()  # Используйте соответствующую базу данных
        course = session.query(Course).filter(Course.id == course_id).first()
        session.close()
        
        if course:
            admin_data[user_id]['course_id'] = course_id
            admin_data[user_id]['step'] = 11
            await bot.send_message(user_id, "Теперь отправьте количество домашних заданий.")
        else:
            await bot.send_message(user_id, "Курс с таким ID не найден.")
    except ValueError:
        await bot.send_message(user_id, "Пожалуйста, введите корректный ID курса.")

@dp.message_handler(lambda message: message.from_user.id in admin_data and admin_data[message.from_user.id]['step'] == 11)
async def process_homework_count(message: types.Message):
    user_id = message.from_user.id
    try:
        count = int(message.text)
        admin_data[user_id]['homework_count'] = count
        admin_data[user_id]['current_homework'] = 1
        admin_data[user_id]['step'] = 12
        await bot.send_message(user_id, f"Введите заголовок домашнего задания {admin_data[user_id]['current_homework']} из {count}.")
    except ValueError:
        await bot.send_message(user_id, "Пожалуйста, введите корректное количество домашних заданий.")


@dp.message_handler(lambda message: message.from_user.id in admin_data and admin_data[message.from_user.id]['step'] == 12)
async def process_homework_details(message: types.Message):
    user_id = message.from_user.id
    data = admin_data[user_id]
    
    # Получение текущего задания
    current_homework = data['current_homework']
    homework_count = data['homework_count']
    
    if current_homework < homework_count:
        if 'homework' not in data:
            data['homework'] = {}
        
        if 'title' not in data['homework']:
            data['homework']['title'] = message.text
            await bot.send_message(user_id, "Теперь отправьте описание домашнего задания.")
        elif 'description' not in data['homework']:
            data['homework']['description'] = message.text
            await bot.send_message(user_id, "Теперь отправьте текст задания.")
        elif 'task' not in data['homework']:
            data['homework']['task'] = message.text
            await bot.send_message(user_id, "Теперь отправьте ответ на задание.")
        elif 'answer' not in data['homework']:
            data['homework']['answer'] = message.text
            
            # Сохранение домашнего задания
            session = SessionLocalBot()  # Используйте соответствующую базу данных
            new_homework = Assignment(
                course_id=data['course_id'],
                title=data['homework']['title'],
                description=data['homework']['description'],
                task=data['homework']['task'],
                answer=data['homework']['answer']
            )
            session.add(new_homework)
            session.commit()
            session.close()
            
            # Переход к следующему заданию
            data['current_homework'] += 1
            
            if data['current_homework'] < homework_count:
                await bot.send_message(user_id, "Теперь отправьте название следующего домашнего задания.")
            else:
                await bot.send_message(user_id, "Все домашние задания успешно добавлены.")
                del admin_data[user_id]
        else:
            await bot.send_message(user_id, "Все домашние задания успешно добавлены.")
            del admin_data[user_id]
    else:
        await bot.send_message(user_id, "Все домашние задания успешно добавлены.")
        del admin_data[user_id]

# Запуск бота
if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)