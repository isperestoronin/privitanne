import paho.mqtt.client as mqtt
import tkinter as tk
from tkinter import scrolledtext, simpledialog, messagebox, filedialog
import threading
import json
import time
import os
import base64
from datetime import datetime
import io
import subprocess
import sys
import shutil

# Попробуем импортировать PIL, если нет - пропускаем
try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("PIL не установлен. Фото будут отображаться как ссылки.")

# Попробуем импортировать уведомления для Windows
try:
    from win10toast import ToastNotifier
    TOAST_AVAILABLE = True
except ImportError:
    TOAST_AVAILABLE = False

class InternetMessenger:
    def __init__(self):
        # Уникальный ID чата
        self.CHAT_ROOM = "my_secret_chat_room_2024"
        self.username = None
        
        # Публичный MQTT брокер
        self.BROKER = "broker.emqx.io"
        self.PORT = 1883
        
        # Папки
        self.history_dir = "chat_histories"
        self.files_dir = "received_files"
        self.backup_dir = "backups"
        
        for dir_path in [self.history_dir, self.files_dir, self.backup_dir]:
            if not os.path.exists(dir_path):
                os.makedirs(dir_path)
        
        # MQTT клиент
        self.client = mqtt.Client()
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.max_inflight_messages_set(100)
        
        # GUI
        self.create_gui()
        
        # Подключение
        self.connect_to_broker()
        
        # Кэш
        self.photo_cache = {}
        
        # Уведомления
        self.notifications_enabled = True
        self.last_notification_time = 0
        
        # Для уведомлений Windows
        self.toaster = None
        if TOAST_AVAILABLE:
            self.toaster = ToastNotifier()
    
    def create_gui(self):
        self.window = tk.Tk()
        self.window.title("Прывiтанне!!")
        self.window.geometry("800x700")
        
        # Верхняя панель
        top_frame = tk.Frame(self.window)
        top_frame.pack(padx=10, pady=5, fill=tk.X)
        
        # Кнопки
        buttons = [
            ("💾 Сохранить", self.save_history),
            ("📂 Загрузить", self.load_history),
            ("🗑 Очистить", self.clear_chat),
            ("🔍 Поиск", self.search_messages),
            ("💽 Бэкап", self.create_backup),
            ("🔄 Восст.", self.restore_backup),
            ("📷 Фото", self.send_photo),
            ("🎥 Видео", self.send_video),
            ("📎 Файл", self.send_file)
        ]
        
        for text, command in buttons:
            btn = tk.Button(top_frame, text=text, command=command)
            btn.pack(side=tk.LEFT, padx=2)
        
        # Кнопка уведомлений
        self.notify_btn = tk.Button(top_frame, text="🔔 Увед. ВКЛ", command=self.toggle_notifications)
        self.notify_btn.pack(side=tk.LEFT, padx=2)
        
        # Чат дисплей
        self.chat_display = scrolledtext.ScrolledText(self.window, wrap=tk.WORD, font=("Arial", 10))
        self.chat_display.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
        self.chat_display.config(state=tk.DISABLED)
        
        # Теги для форматирования
        self.chat_display.tag_config("system", foreground="gray", font=("Arial", 9, "italic"))
        self.chat_display.tag_config("my_message", foreground="blue")
        self.chat_display.tag_config("other_message", foreground="black")
        self.chat_display.tag_config("highlight", background="yellow")
        
        # Ввод сообщения
        input_frame = tk.Frame(self.window)
        input_frame.pack(padx=10, pady=5, fill=tk.X)
        
        self.message_entry = tk.Entry(input_frame, font=("Arial", 10))
        self.message_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        self.message_entry.bind("<Return>", self.send_message)
        
        self.send_btn = tk.Button(input_frame, text="Отправить", command=self.send_message)
        self.send_btn.pack(side=tk.LEFT)
        
        # Статус
        self.status_label = tk.Label(self.window, text="Подключение...", fg="blue")
        self.status_label.pack(pady=5)
        
        self.window.protocol("WM_DELETE_WINDOW", self.on_closing)
    
    def connect_to_broker(self):
        def connect():
            try:
                self.client.connect(self.BROKER, self.PORT, 60)
                self.client.loop_start()
                self.window.after(100, self.ask_username)
            except Exception as e:
                self.window.after(0, self.update_status, f"Ошибка: {e}", "red")
        
        thread = threading.Thread(target=connect, daemon=True)
        thread.start()
    
    def ask_username(self):
        username = simpledialog.askstring("Имя", "Введите ваше имя:", parent=self.window)
        if username:
            self.username = username.strip()
        else:
            self.username = f"User_{int(time.time())}"
        
        self.window.title(f"Мессенджер - {self.username}")
        self.subscribe_to_chat()
        self.load_last_history()
    
    def subscribe_to_chat(self):
        self.client.subscribe(f"chat/{self.CHAT_ROOM}")
        self.update_status("Онлайн ✓", "green")
        self.add_message(f"🌟 {self.username} присоединился к чату!", "system")
        self.send_system_message(f"{self.username} присоединился")
    
    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.window.after(0, self.update_status, "Подключено", "blue")
        else:
            self.window.after(0, self.update_status, f"Ошибка {rc}", "red")
    
    def on_message(self, client, userdata, msg):
        try:
            data = json.loads(msg.payload.decode())
            sender = data.get('sender')
            msg_type = data.get('type', 'message')
            timestamp = data.get('timestamp', time.time())
            
            # Сохраняем в историю
            self.save_to_history(data)
            
            # Показываем уведомление (только для чужих сообщений)
            if sender != self.username and msg_type == 'message' and self.notifications_enabled:
                self.show_notification(sender, data.get('message', ''))
            
            # Отображаем в чате
            if sender != self.username:
                if msg_type == 'system':
                    self.window.after(0, self.add_message, f"📢 {data['message']}", "system")
                elif msg_type == 'message':
                    time_str = datetime.fromtimestamp(timestamp).strftime('%H:%M')
                    text = f"[{time_str}] {sender}: {data.get('message', '')}"
                    self.window.after(0, self.add_message, text, "other_message")
                elif msg_type in ['photo', 'video', 'file']:
                    self.window.after(0, self.display_media, data, sender, timestamp)
                    
        except Exception as e:
            print(f"Ошибка: {e}")
    
    def display_media(self, data, sender, timestamp):
        """Отображение медиафайлов"""
        time_str = datetime.fromtimestamp(timestamp).strftime('%H:%M')
        msg_type = data['type']
        file_name = data.get('file_name', 'file')
        file_size = data.get('file_size', 0)
        
        icon = "📷" if msg_type == 'photo' else "🎬" if msg_type == 'video' else "📎"
        
        self.chat_display.config(state=tk.NORMAL)
        self.chat_display.insert(tk.END, f"[{time_str}] {sender}: {icon} {file_name} ({file_size/1024:.1f} KB)\n")
        
        # Сохраняем файл
        file_data = base64.b64decode(data['file_data'])
        saved_path = self.save_file(file_name, file_data, sender)
        
        if saved_path:
            # Создаем кнопку
            btn_frame = tk.Frame(self.chat_display)
            open_btn = tk.Button(btn_frame, text="📂 Открыть", 
                                command=lambda: self.open_file(saved_path))
            open_btn.pack(side=tk.LEFT, padx=2)
            
            save_btn = tk.Button(btn_frame, text="💾 Сохранить",
                                command=lambda: self.save_file_as(saved_path))
            save_btn.pack(side=tk.LEFT, padx=2)
            
            self.chat_display.window_create(tk.END, window=btn_frame)
            self.chat_display.insert(tk.END, "\n")
        
        self.chat_display.see(tk.END)
        self.chat_display.config(state=tk.DISABLED)
    
    def save_file(self, filename, data, sender):
        """Сохранение файла на диск"""
        base, ext = os.path.splitext(filename)
        new_name = f"{base}_{int(time.time())}_{sender}{ext}"
        new_name = "".join(c for c in new_name if c.isalnum() or c in '._-')
        path = os.path.join(self.files_dir, new_name)
        
        try:
            with open(path, 'wb') as f:
                f.write(data)
            return path
        except:
            return None
    
    def send_message(self, event=None):
        """Отправка текстового сообщения"""
        message = self.message_entry.get().strip()
        if message and self.username:
            data = {
                'sender': self.username,
                'message': message,
                'type': 'message',
                'timestamp': time.time()
            }
            self.client.publish(f"chat/{self.CHAT_ROOM}", json.dumps(data))
            
            # Показываем свое сообщение
            time_str = datetime.now().strftime('%H:%M')
            self.add_message(f"[{time_str}] Вы: {message}", "my_message")
            self.message_entry.delete(0, tk.END)
            
            # Сохраняем
            self.save_to_history(data)
    
    def send_photo(self):
        """Отправка фото"""
        path = filedialog.askopenfilename(filetypes=[("Изображения", "*.jpg *.jpeg *.png *.gif")])
        if path:
            self.send_file_generic(path, "photo")
    
    def send_video(self):
        """Отправка видео"""
        path = filedialog.askopenfilename(filetypes=[("Видео", "*.mp4 *.avi *.mov")])
        if path:
            self.send_file_generic(path, "video")
    
    def send_file(self):
        """Отправка файла"""
        path = filedialog.askopenfilename()
        if path:
            self.send_file_generic(path, "file")
    
    def send_file_generic(self, file_path, file_type):
        """Общая отправка файлов"""
        try:
            size = os.path.getsize(file_path)
            max_size = 10 * 1024 * 1024
            
            if size > max_size:
                messagebox.showerror("Ошибка", f"Файл >10MB ({size/1024/1024:.1f}MB)")
                return
            
            with open(file_path, 'rb') as f:
                file_data = base64.b64encode(f.read()).decode()
            
            data = {
                'sender': self.username,
                'type': file_type,
                'file_name': os.path.basename(file_path),
                'file_data': file_data,
                'file_size': size,
                'timestamp': time.time()
            }
            
            self.client.publish(f"chat/{self.CHAT_ROOM}", json.dumps(data))
            
            # Показываем
            time_str = datetime.now().strftime('%H:%M')
            icon = "📷" if file_type == 'photo' else "🎬" if file_type == 'video' else "📎"
            self.add_message(f"[{time_str}] Вы отправили: {icon} {os.path.basename(file_path)}", "my_message")
            
            self.save_to_history(data)
            self.update_status(f"Отправлено: {os.path.basename(file_path)}", "green")
            
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось отправить: {e}")
    
    def add_message(self, text, tag=None):
        """Добавление сообщения в чат"""
        self.chat_display.config(state=tk.NORMAL)
        if tag:
            self.chat_display.insert(tk.END, text + "\n", tag)
        else:
            self.chat_display.insert(tk.END, text + "\n")
        self.chat_display.see(tk.END)
        self.chat_display.config(state=tk.DISABLED)
    
    def send_system_message(self, text):
        """Отправка системного сообщения"""
        data = {
            'sender': 'system',
            'message': text,
            'type': 'system',
            'timestamp': time.time()
        }
        self.client.publish(f"chat/{self.CHAT_ROOM}", json.dumps(data))
    
    def save_to_history(self, data):
        """Сохранение в историю"""
        if not self.username:
            return
        
        file_path = os.path.join(self.history_dir, f"{self.username}_history.json")
        
        try:
            history = []
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    history = json.load(f)
            
            history.append(data)
            
            # Оставляем последние 5000 сообщений
            if len(history) > 5000:
                history = history[-5000:]
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Ошибка сохранения: {e}")
    
    def load_last_history(self):
        """Загрузка последних сообщений"""
        file_path = os.path.join(self.history_dir, f"{self.username}_history.json")
        
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    history = json.load(f)
                
                # Последние 50 сообщений
                for msg in history[-50:]:
                    if msg.get('type') == 'system':
                        self.add_message(f"📢 {msg['message']}", "system")
                    elif msg.get('type') == 'message':
                        time_str = datetime.fromtimestamp(msg['timestamp']).strftime('%H:%M')
                        sender = "Вы" if msg.get('sender') == self.username else msg.get('sender')
                        self.add_message(f"[{time_str}] {sender}: {msg.get('message', '')}")
                
                self.add_message(f"\n--- Загружено {len(history[-50:])} сообщений ---\n", "system")
            except:
                pass
    
    # ============= ПОИСК =============
    def search_messages(self):
        """Поиск по истории"""
        query = simpledialog.askstring("Поиск", "Введите текст для поиска:", parent=self.window)
        if not query:
            return
        
        file_path = os.path.join(self.history_dir, f"{self.username}_history.json")
        if not os.path.exists(file_path):
            messagebox.showinfo("Поиск", "История не найдена")
            return
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                history = json.load(f)
            
            results = []
            query_lower = query.lower()
            
            for msg in history:
                if msg.get('type') == 'message':
                    if query_lower in msg.get('message', '').lower():
                        results.append(msg)
            
            if not results:
                messagebox.showinfo("Поиск", f"Ничего не найдено по запросу: {query}")
                return
            
            # Показываем результаты
            result_window = tk.Toplevel(self.window)
            result_window.title(f"Результаты поиска: {len(results)}")
            result_window.geometry("600x400")
            
            text_area = scrolledtext.ScrolledText(result_window, wrap=tk.WORD)
            text_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            
            for msg in results:
                time_str = datetime.fromtimestamp(msg['timestamp']).strftime('%Y-%m-%d %H:%M:%S')
                text_area.insert(tk.END, f"[{time_str}] {msg['sender']}: {msg['message']}\n")
                text_area.insert(tk.END, "-" * 50 + "\n")
            
            text_area.config(state=tk.DISABLED)
            
        except Exception as e:
            messagebox.showerror("Ошибка", f"Ошибка поиска: {e}")
    
    # ============= УВЕДОМЛЕНИЯ =============
    def toggle_notifications(self):
        """Вкл/выкл уведомлений"""
        self.notifications_enabled = not self.notifications_enabled
        if self.notifications_enabled:
            self.notify_btn.config(text="🔔 Увед. ВКЛ", bg="lightgreen")
            self.update_status("Уведомления включены", "green")
        else:
            self.notify_btn.config(text="🔕 Увед. ВЫКЛ", bg="lightgray")
            self.update_status("Уведомления выключены", "orange")
    
    def show_notification(self, sender, message):
        """Показ уведомления"""
        # Ограничение частоты
        if time.time() - self.last_notification_time < 2:
            return
        self.last_notification_time = time.time()
        
        if len(message) > 50:
            message = message[:47] + "..."
        
        try:
            if sys.platform == 'win32' and TOAST_AVAILABLE and self.toaster:
                self.toaster.show_toast(
                    f"📨 {sender}",
                    message,
                    duration=3,
                    threaded=True
                )
            elif sys.platform == 'darwin':
                subprocess.run(['osascript', '-e', f'display notification "{message}" with title "{sender}"'])
            elif sys.platform.startswith('linux'):
                subprocess.run(['notify-send', sender, message])
        except:
            pass
    
    # ============= БЭКАП =============
    def create_backup(self):
        """Создание бэкапа"""
        if not self.username:
            messagebox.showwarning("Ошибка", "Имя не определено")
            return
        
        backup_name = f"backup_{self.username}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        backup_path = os.path.join(self.backup_dir, backup_name)
        
        try:
            # Копируем историю
            history_file = os.path.join(self.history_dir, f"{self.username}_history.json")
            if os.path.exists(history_file):
                shutil.copy2(history_file, backup_path + "_history.json")
            
            # Создаем архив
            zip_path = shutil.make_archive(backup_path, 'zip', self.history_dir)
            
            messagebox.showinfo("Бэкап", f"Создан: {zip_path}")
            self.update_status(f"Бэкап создан", "green")
            
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось создать бэкап: {e}")
    
    def restore_backup(self):
        """Восстановление из бэкапа"""
        file_path = filedialog.askopenfilename(
            filetypes=[("ZIP files", "*.zip")],
            initialdir=self.backup_dir
        )
        
        if not file_path:
            return
        
        if messagebox.askyesno("Восстановление", "Это заменит текущую историю. Продолжить?"):
            try:
                # Распаковываем
                extract_path = os.path.join(self.backup_dir, "temp_restore")
                shutil.unpack_archive(file_path, extract_path, 'zip')
                
                # Восстанавливаем
                for file in os.listdir(extract_path):
                    if file.endswith('_history.json'):
                        shutil.copy2(
                            os.path.join(extract_path, file),
                            os.path.join(self.history_dir, f"{self.username}_history.json")
                        )
                
                # Очищаем
                shutil.rmtree(extract_path)
                
                messagebox.showinfo("Успех", "История восстановлена. Перезапустите приложение.")
                
            except Exception as e:
                messagebox.showerror("Ошибка", f"Не удалось восстановить: {e}")
    
    # ============= ДРУГИЕ ФУНКЦИИ =============
    def save_history(self):
        """Сохранение истории в файл"""
        filename = simpledialog.askstring("Сохранить", "Имя файла:", parent=self.window)
        if filename:
            src = os.path.join(self.history_dir, f"{self.username}_history.json")
            dst = os.path.join(self.history_dir, f"{filename}.json")
            if os.path.exists(src):
                shutil.copy2(src, dst)
                messagebox.showinfo("Успех", f"Сохранено в {filename}.json")
    
    def load_history(self):
        """Загрузка истории из файла"""
        files = [f for f in os.listdir(self.history_dir) if f.endswith('.json')]
        if not files:
            messagebox.showinfo("Инфо", "Нет сохраненных историй")
            return
        
        # Простой выбор
        load_window = tk.Toplevel(self.window)
        load_window.title("Выберите файл")
        load_window.geometry("300x300")
        
        listbox = tk.Listbox(load_window)
        for f in files:
            listbox.insert(tk.END, f)
        listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        def load():
            selection = listbox.curselection()
            if selection:
                file = files[selection[0]]
                src = os.path.join(self.history_dir, file)
                dst = os.path.join(self.history_dir, f"{self.username}_history.json")
                shutil.copy2(src, dst)
                messagebox.showinfo("Успех", "История загружена. Перезапустите приложение.")
                load_window.destroy()
        
        tk.Button(load_window, text="Загрузить", command=load).pack(pady=10)
    
    def clear_chat(self):
        """Очистка чата"""
        if messagebox.askyesno("Очистка", "Очистить окно чата?"):
            self.chat_display.config(state=tk.NORMAL)
            self.chat_display.delete(1.0, tk.END)
            self.chat_display.config(state=tk.DISABLED)
    
    def open_file(self, path):
        """Открытие файла"""
        try:
            if sys.platform == 'win32':
                os.startfile(path)
            elif sys.platform == 'darwin':
                subprocess.run(['open', path])
            else:
                subprocess.run(['xdg-open', path])
        except:
            pass
    
    def save_file_as(self, src_path):
        """Сохранение файла как..."""
        dst_path = filedialog.asksaveasfilename(initialfile=os.path.basename(src_path))
        if dst_path:
            shutil.copy2(src_path, dst_path)
            messagebox.showinfo("Успех", "Файл сохранен")
    
    def update_status(self, text, color):
        """Обновление статуса"""
        self.status_label.config(text=text, fg=color)
    
    def on_closing(self):
        """Закрытие приложения"""
        if self.username:
            self.send_system_message(f"{self.username} покинул чат")
            time.sleep(0.5)
        self.client.loop_stop()
        self.client.disconnect()
        self.window.destroy()

if __name__ == "__main__":
    # Сначала установите библиотеки:
    # pip install paho-mqtt
    # pip install Pillow (опционально)
    
    messenger = InternetMessenger()
    messenger.window.mainloop()

