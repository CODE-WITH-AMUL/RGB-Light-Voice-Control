from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.progressbar import ProgressBar
from kivy.clock import Clock
from kivy.logger import Logger
from kivy.utils import platform
import threading
import time
import re

# Only import Android-specific modules on Android platform
if platform == 'android':
    from jnius import autoclass, PythonJavaClass, java_method
    from android.permissions import request_permissions, Permission
    
    # Android Components
    SpeechRecognizer = autoclass('android.speech.SpeechRecognizer')
    RecognizerIntent = autoclass('android.speech.RecognizerIntent')
    Intent = autoclass('android.content.Intent')
    PythonActivity = autoclass('org.kivy.android.PythonActivity')
    Context = autoclass('android.content.Context')
    Bundle = autoclass('android.os.Bundle')
else:
    # Mock classes for desktop testing
    class MockJavaClass:
        def __init__(self, *args, **kwargs): pass
        def __getattr__(self, name): return lambda *args, **kwargs: None
    
    SpeechRecognizer = RecognizerIntent = Intent = PythonActivity = Context = Bundle = MockJavaClass

# Enhanced color mappings with more colors
COLOR_MAP = {
    'red': [38000, 9000, 4500, 562, 562, 1687, 562],
    'blue': [38000, 9000, 4500, 562, 1687, 562, 562],
    'green': [38000, 9000, 4500, 1687, 562, 562, 562],
    'white': [38000, 9000, 4500, 562, 562, 562, 1687],
    'yellow': [38000, 9000, 4500, 1687, 562, 1687, 562],
    'purple': [38000, 9000, 4500, 562, 1687, 1687, 1687],
    'orange': [38000, 9000, 4500, 1687, 1687, 562, 562],
    'pink': [38000, 9000, 4500, 1687, 562, 562, 1687]
}

# Command patterns for better recognition
COMMAND_PATTERNS = {
    'on': [
        r"daddy'?s home",
        r"turn on",
        r"lights? on",
        r"power on"
    ],
    'off': [
        r"turn off",
        r"lights? off",
        r"power off",
        r"shut off"
    ],
    'color': [
        r"change to (\w+)",
        r"set (?:color )?to (\w+)",
        r"make it (\w+)",
        r"switch to (\w+)"
    ]
}

class VoiceRecognitionListener(PythonJavaClass):
    __javainterfaces__ = ['android/speech/RecognitionListener']
    __javacontext__ = 'app'

    def __init__(self, callback, error_callback=None):
        super().__init__()
        self.callback = callback
        self.error_callback = error_callback or (lambda x: None)

    @java_method('(Landroid/os/Bundle;)V')
    def onResults(self, results):
        try:
            self.callback(results)
        except Exception as e:
            Logger.error(f"VoiceRecognition: Error in onResults: {e}")
            self.error_callback(f"Processing error: {e}")

    @java_method('(I)V')
    def onError(self, error):
        error_messages = {
            1: "Network timeout",
            2: "Network error", 
            3: "Audio error",
            4: "Server error",
            5: "Client error",
            6: "Speech timeout",
            7: "No match found",
            8: "Recognition service busy",
            9: "Insufficient permissions"
        }
        message = error_messages.get(error, f"Unknown error: {error}")
        Logger.error(f"VoiceRecognition: {message}")
        self.error_callback(message)

    # Required empty methods with proper signatures
    @java_method('(Landroid/os/Bundle;)V')
    def onReadyForSpeech(self, params): 
        Logger.info("VoiceRecognition: Ready for speech")

    @java_method('()V')
    def onBeginningOfSpeech(self): 
        Logger.info("VoiceRecognition: Speech started")

    @java_method('(F)V')
    def onRmsChanged(self, rmsdB): pass

    @java_method('([B)V')
    def onBufferReceived(self, buffer): pass

    @java_method('()V')
    def onEndOfSpeech(self): 
        Logger.info("VoiceRecognition: Speech ended")

    @java_method('(Landroid/os/Bundle;)V')
    def onPartialResults(self, partialResults): pass

    @java_method('(ILandroid/os/Bundle;)V')
    def onEvent(self, eventType, params): pass

class SmartLightControlApp(App):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.ir_manager = None
        self.recognizer = None
        self.is_listening = False
        self.listening_timeout = None
        self.current_color = "white"

    def build(self):
        # Request permissions on Android
        if platform == 'android':
            try:
                request_permissions([Permission.RECORD_AUDIO, Permission.TRANSMIT_IR])
            except Exception as e:
                Logger.error(f"Permission request failed: {e}")
        
        # Main layout
        self.layout = BoxLayout(orientation='vertical', padding=20, spacing=15)
        
        # Title
        title = Label(
            text="🏠 Smart Light Voice Control",
            font_size='24sp',
            size_hint=(1, 0.15),
            bold=True,
            color=(0.2, 0.6, 1, 1)
        )
        
        # Status display
        self.status_label = Label(
            text="Ready! Press the button and speak your command",
            font_size='18sp',
            halign='center',
            valign='middle',
            size_hint=(1, 0.25),
            text_size=(None, None),
            markup=True
        )
        
        # Progress bar for listening feedback
        self.progress_bar = ProgressBar(
            max=100,
            value=0,
            size_hint=(1, 0.1)
        )
        self.progress_bar.opacity = 0
        
        # Main control button
        self.control_btn = Button(
            text="🎤 Start Listening",
            size_hint=(1, 0.2),
            font_size='20sp',
            background_normal='',
            background_color=(0.2, 0.7, 0.3, 1),
            bold=True
        )
        self.control_btn.bind(on_press=self.toggle_listening)
        
        # Info panel
        info_text = (
            "[b]Commands:[/b]\n"
            "• 'Daddy's home' / 'Turn on' - Turn lights on\n"
            "• 'Turn off' - Turn lights off\n"
            f"• 'Change to [color]' - Available colors: {', '.join(COLOR_MAP.keys())}\n"
            f"[b]Current color:[/b] {self.current_color}"
        )
        
        self.info_label = Label(
            text=info_text,
            font_size='14sp',
            size_hint=(1, 0.3),
            halign='left',
            valign='top',
            text_size=(None, None),
            markup=True
        )
        
        # Add widgets to layout
        self.layout.add_widget(title)
        self.layout.add_widget(self.status_label)
        self.layout.add_widget(self.progress_bar)
        self.layout.add_widget(self.control_btn)
        self.layout.add_widget(self.info_label)
        
        return self.layout

    def on_start(self):
        """Initialize IR manager after app starts"""
        if platform == 'android':
            try:
                self.ir_manager = PythonActivity.mActivity.getSystemService(Context.CONSUMER_IR_SERVICE)
                if not self.ir_manager or not self.ir_manager.hasIrEmitter():
                    self.show_error("No IR blaster detected on this device")
                    self.control_btn.disabled = True
                else:
                    Logger.info("IR blaster initialized successfully")
            except Exception as e:
                self.show_error(f"IR initialization failed: {e}")
                self.control_btn.disabled = True
        else:
            self.show_status("Running in desktop mode - IR features disabled")

    def toggle_listening(self, instance):
        """Toggle voice recognition on/off"""
        if self.is_listening:
            self.stop_listening()
        else:
            self.start_listening()

    def start_listening(self):
        """Start voice recognition"""
        if platform != 'android':
            self.show_status("Voice recognition only works on Android devices")
            return
            
        try:
            self.is_listening = True
            self.control_btn.text = "🔴 Listening... (Speak Now)"
            self.control_btn.background_color = (0.9, 0.2, 0.2, 1)
            self.show_status("🎤 Listening for your command...")
            
            # Show progress animation
            self.progress_bar.opacity = 1
            self.animate_progress()
            
            # Create speech recognizer
            self.recognizer = SpeechRecognizer.createSpeechRecognizer(PythonActivity.mActivity)
            listener = VoiceRecognitionListener(self.process_speech, self.handle_recognition_error)
            self.recognizer.setRecognitionListener(listener)
            
            # Configure recognition intent
            intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
            intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            intent.putExtra(RecognizerIntent.EXTRA_PROMPT, "Speak your light command")
            intent.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 5)
            intent.putExtra(RecognizerIntent.EXTRA_PARTIAL, True)
            
            self.recognizer.startListening(intent)
            
            # Set timeout for listening
            self.listening_timeout = Clock.schedule_once(self.listening_timeout_callback, 10)
            
        except Exception as e:
            Logger.error(f"Failed to start listening: {e}")
            self.show_error(f"Failed to start voice recognition: {e}")
            self.stop_listening()

    def stop_listening(self):
        """Stop voice recognition"""
        try:
            if self.recognizer:
                self.recognizer.destroy()
                self.recognizer = None
                
            if self.listening_timeout:
                self.listening_timeout.cancel()
                self.listening_timeout = None
                
            self.is_listening = False
            self.control_btn.text = "🎤 Start Listening"
            self.control_btn.background_color = (0.2, 0.7, 0.3, 1)
            self.progress_bar.opacity = 0
            
        except Exception as e:
            Logger.error(f"Error stopping recognition: {e}")

    def listening_timeout_callback(self, dt):
        """Handle listening timeout"""
        self.show_status("Listening timeout - please try again")
        self.stop_listening()

    def animate_progress(self):
        """Animate progress bar during listening"""
        if self.is_listening:
            self.progress_bar.value = (self.progress_bar.value + 10) % 100
            Clock.schedule_once(lambda dt: self.animate_progress(), 0.2)

    def process_speech(self, results):
        """Process speech recognition results"""
        try:
            if platform != 'android':
                return
                
            matches = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
            if not matches or matches.size() == 0:
                self.show_status("No speech detected - please try again")
                self.stop_listening()
                return
            
            # Try all recognition results
            command_executed = False
            for i in range(matches.size()):
                command = matches.get(i).lower().strip()
                Logger.info(f"Processing command: '{command}'")
                
                if self.execute_command(command):
                    command_executed = True
                    break
            
            if not command_executed:
                self.show_status(f"Command not recognized. Try: 'Turn on', 'Turn off', or 'Change to [color]'")
                
        except Exception as e:
            Logger.error(f"Error processing speech: {e}")
            self.show_error(f"Speech processing error: {e}")
        finally:
            Clock.schedule_once(lambda dt: self.stop_listening(), 1)

    def execute_command(self, command):
        """Execute voice command"""
        try:
            # Check for ON commands
            for pattern in COMMAND_PATTERNS['on']:
                if re.search(pattern, command, re.IGNORECASE):
                    self.send_ir_code([38000, 9000, 4500, 562, 562, 562, 562], "Turning lights ON")
                    return True
            
            # Check for OFF commands  
            for pattern in COMMAND_PATTERNS['off']:
                if re.search(pattern, command, re.IGNORECASE):
                    self.send_ir_code([38000, 9000, 4500, 562, 1687, 1687, 562], "Turning lights OFF")
                    return True
            
            # Check for color commands
            for pattern in COMMAND_PATTERNS['color']:
                match = re.search(pattern, command, re.IGNORECASE)
                if match:
                    color = match.group(1).lower()
                    if color in COLOR_MAP:
                        self.current_color = color
                        self.update_info_panel()
                        self.send_ir_code(COLOR_MAP[color], f"Changing to {color.upper()}")
                        return True
                    else:
                        self.show_status(f"Color '{color}' not available. Try: {', '.join(COLOR_MAP.keys())}")
                        return False
            
            return False
            
        except Exception as e:
            Logger.error(f"Error executing command: {e}")
            self.show_error(f"Command execution error: {e}")
            return False

    def send_ir_code(self, pattern, action_text):
        """Send IR code with improved error handling"""
        try:
            if platform != 'android':
                self.show_status(f"[Desktop Mode] {action_text}")
                return
                
            if not self.ir_manager:
                self.show_error("IR manager not available")
                return
                
            if not self.ir_manager.hasIrEmitter():
                self.show_error("No IR emitter found")
                return
            
            # Convert pattern to proper format
            frequency = pattern[0]
            signal_pattern = pattern[1:]
            
            # Transmit IR signal
            self.ir_manager.transmit(frequency, signal_pattern)
            self.show_success(f"✅ {action_text}")
            
            Logger.info(f"IR signal sent: {action_text}")
            
        except Exception as e:
            Logger.error(f"IR transmission error: {e}")
            self.show_error(f"Failed to send IR signal: {e}")

    def handle_recognition_error(self, error_message):
        """Handle voice recognition errors"""
        self.show_error(f"Voice recognition error: {error_message}")
        Clock.schedule_once(lambda dt: self.stop_listening(), 1)

    def show_status(self, message):
        """Show status message"""
        self.status_label.text = message
        self.status_label.color = (1, 1, 1, 1)  # White

    def show_success(self, message):
        """Show success message"""
        self.status_label.text = message
        self.status_label.color = (0.2, 0.8, 0.2, 1)  # Green

    def show_error(self, message):
        """Show error message"""
        self.status_label.text = f"❌ {message}"
        self.status_label.color = (0.9, 0.2, 0.2, 1)  # Red
        Logger.error(message)

    def update_info_panel(self):
        """Update the info panel with current settings"""
        info_text = (
            "[b]Commands:[/b]\n"
            "• 'Daddy's home' / 'Turn on' - Turn lights on\n"
            "• 'Turn off' - Turn lights off\n"
            f"• 'Change to [color]' - Available colors: {', '.join(COLOR_MAP.keys())}\n"
            f"[b]Current color:[/b] {self.current_color}"
        )
        self.info_label.text = info_text

    def on_stop(self):
        """Clean up when app closes"""
        try:
            self.stop_listening()
        except:
            pass

if __name__ == '__main__':
    SmartLightControlApp().run()