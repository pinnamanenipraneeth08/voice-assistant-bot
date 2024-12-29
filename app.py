from flask import Flask, render_template
from flask_socketio import SocketIO, emit
import os
import time
import pywhatkit
import requests
import pygame
import speech_recognition as sr
from gtts import gTTS
import psutil
from threading import Thread
import logging
import subprocess
import platform
import webbrowser
from datetime import datetime, timedelta
import json
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = 'voiceassistant123!' 
socketio = SocketIO(app, cors_allowed_origins="*")

pygame.mixer.init()

if not os.path.exists("sound"):
    os.makedirs("sound")

class VoiceAssistant:
    def __init__(self):
        self.recognizer = sr.Recognizer()
        self.is_listening = False
        self.reminders = []
        self.reminders_file = "reminders.json"
        
        self.load_reminders()
        
        
        Thread(target=self.check_reminders, daemon=True).start()
        
        self.app_commands = {
            'calculator': {
                'windows': 'calc.exe',
                'linux': 'gnome-calculator',
                'darwin': 'Calculator.app'
            },
            'calendar': {
                'windows': 'outlookcal.exe',
                'linux': 'gnome-calendar',
                'darwin': 'Calendar.app'
            },
            'notepad': {
                'windows': 'notepad.exe',
                'linux': 'gedit',
                'darwin': 'TextEdit.app'
            }
        }
        
        self.opened_processes = {}

    def load_reminders(self):
        """Load reminders from file."""
        try:
            if os.path.exists(self.reminders_file):
                with open(self.reminders_file, 'r') as f:
                    saved_reminders = json.load(f)
                    for reminder in saved_reminders:
                        reminder['time'] = datetime.fromisoformat(reminder['time'])
                    self.reminders = saved_reminders
        except Exception as e:
            logger.error(f"Error loading reminders: {str(e)}")

    def save_reminders(self):
        """Save reminders to file."""
        try:
            
            reminders_to_save = []
            for reminder in self.reminders:
                reminder_copy = reminder.copy()
                reminder_copy['time'] = reminder_copy['time'].isoformat()
                reminders_to_save.append(reminder_copy)
                
            with open(self.reminders_file, 'w') as f:
                json.dump(reminders_to_save, f)
        except Exception as e:
            logger.error(f"Error saving reminders: {str(e)}")

    def parse_time(self, time_str):
        """Parse time string into timedelta."""
        time_val = int(''.join(filter(str.isdigit, time_str)))
        
        if 'hour' in time_str:
            return timedelta(hours=time_val)
        elif 'day' in time_str:
            return timedelta(days=time_val)
        else:  
            return timedelta(minutes=time_val)

    def check_reminders(self):
        """Periodically check for due reminders."""
        while True:
            current_time = datetime.now()
            due_reminders = [r for r in self.reminders if r['time'] <= current_time]
            
            for reminder in due_reminders:
                self.speak(f"Reminder: {reminder['message']}")
                self.reminders.remove(reminder)
                self.save_reminders()
            
            time.sleep(30) 

    def add_reminder(self, message, time_delta):
        """Add a new reminder."""
        reminder_time = datetime.now() + time_delta
        reminder = {
            'id': len(self.reminders) + 1,
            'message': message,
            'time': reminder_time
        }
        self.reminders.append(reminder)
        self.save_reminders()
        return reminder

    def cancel_reminder(self, reminder_id):
        """Cancel a reminder by ID."""
        try:
            reminder_id = int(reminder_id)
            for reminder in self.reminders:
                if reminder['id'] == reminder_id:
                    self.reminders.remove(reminder)
                    self.save_reminders()
                    return True
            return False
        except Exception as e:
            logger.error(f"Error canceling reminder: {str(e)}")
            return False

    def list_reminders(self):
        """List all active reminders."""
        if not self.reminders:
            return "You have no active reminders."
        
        reminder_list = []
        for reminder in self.reminders:
            time_str = reminder['time'].strftime('%I:%M %p on %B %d')
            reminder_list.append(f"Reminder {reminder['id']}: {reminder['message']} at {time_str}")
        
        return "\n".join(reminder_list)

    def search_web(self, query):
        """Search the web using default browser and Google."""
        try:
            search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
            webbrowser.open(search_url)
            return True
        except Exception as e:
            logger.error(f"Error searching web: {str(e)}")
            return False
        
    def open_application(self, app_name):
        """Opens the specified application based on the operating system."""
        try:
            current_os = platform.system().lower()
            if app_name not in self.app_commands:
                return False
            
            if current_os == 'windows':
                process = subprocess.Popen([self.app_commands[app_name]['windows']])
            elif current_os == 'linux':
                process = subprocess.Popen([self.app_commands[app_name]['linux']])
            elif current_os == 'darwin':  # macOS
                subprocess.Popen(['open', '-a', self.app_commands[app_name]['darwin']])
                return True
            else:
                return False
            
            self.opened_processes[app_name] = process
            return True
            
        except Exception as e:
            logger.error(f"Error opening application {app_name}: {str(e)}")
            return False

    def close_application(self, app_name):
        """Closes the specified application if it was opened by the assistant."""
        try:
            if app_name in self.opened_processes:
                process = self.opened_processes[app_name]
                process.terminate()
                process.wait(timeout=5)  
                del self.opened_processes[app_name]
                return True
            return False
        except Exception as e:
            logger.error(f"Error closing application {app_name}: {str(e)}")
            return False

    def speak(self, text):
        """Convert text to speech and play it."""
        try:
            logger.info(f"Assistant speaking: {text}")
            socketio.emit('assistant_response', {'response': text})
            
            tts = gTTS(text=text, lang='en', slow=False)
            audio_file = os.path.join("sound", "response.mp3")
            tts.save(audio_file)
            
            pygame.mixer.music.load(audio_file)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.1)
            
            socketio.emit('assistant_done_speaking')
        except Exception as e:
            logger.error(f"Error in speak function: {str(e)}")
            socketio.emit('error', {'error': str(e)})

    def listen(self):
        """Listen for speech input."""
        try:
            with sr.Microphone() as source:
                logger.info("Listening for speech...")
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = self.recognizer.listen(source, timeout=5, phrase_time_limit=5)
                text = self.recognizer.recognize_google(audio).lower()
                logger.info(f"Recognized speech: {text}")
                return text
        except sr.WaitTimeoutError:
            return None
        except sr.UnknownValueError:
            return None
        except Exception as e:
            logger.error(f"Error in listen function: {str(e)}")
            return None

    def process_command(self, text):
        """Process voice commands."""
        if not text:
            return True

        if "remind me to" in text:
            try:
                
                parts = text.split("remind me to")[1].strip().split(" in ")
                message = parts[0].strip()
                time_str = parts[1].strip()
                
                time_delta = self.parse_time(time_str)
                
                reminder = self.add_reminder(message, time_delta)
                time_str = reminder['time'].strftime('%I:%M %p on %B %d')
                self.speak(f"Okay, I'll remind you to {message} at {time_str}. This is reminder number {reminder['id']}.")
                return True
            except Exception as e:
                logger.error(f"Error setting reminder: {str(e)}")
                self.speak("Sorry, I couldn't set that reminder. Please try again with a format like 'remind me to take medicine in 5 minutes'.")
                return True

        elif "cancel reminder" in text:
            try:
                
                reminder_id = re.search(r'\d+', text).group()
                if self.cancel_reminder(reminder_id):
                    self.speak(f"Cancelled reminder {reminder_id}")
                else:
                    self.speak(f"Couldn't find reminder {reminder_id}")
                return True
            except Exception as e:
                logger.error(f"Error canceling reminder: {str(e)}")
                self.speak("Sorry, I couldn't cancel that reminder. Please try again with a format like 'cancel reminder 1'.")
                return True

        elif "list reminders" in text:
            reminder_list = self.list_reminders()
            self.speak(reminder_list)
            return True

        elif text.startswith("open "):
            app_name = text.replace("open ", "").strip()
            if app_name in self.app_commands:
                if self.open_application(app_name):
                    self.speak(f"Opening {app_name}")
                else:
                    self.speak(f"Sorry, I couldn't open {app_name}")
                return True

        elif text.startswith("close "):
            app_name = text.replace("close ", "").strip()
            if app_name in self.app_commands:
                if self.close_application(app_name):
                    self.speak(f"Closing {app_name}")
                else:
                    self.speak(f"Sorry, I couldn't close {app_name}")
                return True

        elif "hello" in text or "hi" in text:
            self.speak("Hello! How can I help you today?")
        
        elif "how are you" in text:
            self.speak("I'm doing well, thank you for asking! How are you?")
        
        elif "goodbye" in text or "bye" in text or "quit" in text or "exit" in text:
            self.speak("Goodbye! Have a great day!")
            return False
        
        elif "search" in text:
            search_query = text.replace("search", "").strip()
            self.speak(f"Searching for {search_query}")
            pywhatkit.search(search_query)
        
        elif "youtube" in text:
            search_query = text.replace("youtube", "").strip()
            self.speak(f"Playing {search_query} on YouTube")
            pywhatkit.playonyt(search_query)
        
        elif "joke" in text:
            try:
                response = requests.get("https://v2.jokeapi.dev/joke/Programming?safe-mode")
                if response.status_code == 200:
                    joke_data = response.json()
                    if joke_data["type"] == "single":
                        self.speak(joke_data["joke"])
                    else:
                        self.speak(f"{joke_data['setup']} ... {joke_data['delivery']}")
            except Exception as e:
                self.speak("Sorry, I couldn't fetch a joke right now.")
        
        else:
            
            self.speak(f"I'll search the web for information about: {text}")
            if self.search_web(text):
                logger.info(f"Searching web for: {text}")
            else:
                self.speak("Sorry, I couldn't perform the web search.")
        
        return True

assistant = VoiceAssistant()

@app.route('/')
def index():
    return render_template('./index.html')

@socketio.on('connect')
def handle_connect():
    logger.info("Client connected")

@socketio.on('disconnect')
def handle_disconnect():
    logger.info("Client disconnected")

@socketio.on('start_listening')
def handle_start_listening():
    def listening_loop():
        assistant.is_listening = True
        while assistant.is_listening:
            text = assistant.listen()
            if text:
                socketio.emit('recognized_speech', {'text': text})
                if not assistant.process_command(text):
                    assistant.is_listening = False
                    break
    
    Thread(target=listening_loop).start()

@socketio.on('stop_listening')
def handle_stop_listening():
    assistant.is_listening = False
    logger.info("Stopped listening")

if __name__ == '__main__':
    
    os.system('cls' if os.name == 'nt' else 'clear')
    
    print("\n=== Voice Assistant Starting ===")
    print("Server is running at:")
    print("http://localhost:5000")
    print("===========================\n")
    
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, allow_unsafe_werkzeug=True)