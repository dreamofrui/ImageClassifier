import sys
import tkinter as tk
from tkinter import messagebox
from pathlib import Path
from config_manager import ConfigManager
from image_classifier import ImageClassifier


class ARSToolkit:
    def __init__(self):
        try:
            self.config_manager = ConfigManager("config.json")
        except Exception as e:
            messagebox.showerror("配置错误", f"无法加载配置文件: {e}")
            sys.exit(1)
        
        self.root = tk.Tk()
        self.root.title("ARS 工具集")
        self.root.geometry("600x400")
        self.root.configure(bg='#1e1e1e')
        
        self.setup_ui()
    
    def setup_ui(self):
        title_frame = tk.Frame(self.root, bg='#0d7377', padx=20, pady=20)
        title_frame.pack(side=tk.TOP, fill=tk.X)
        
        tk.Label(title_frame, text="ARS 工具集", 
                font=('Arial', 24, 'bold'), bg='#0d7377', fg='white').pack()
        tk.Label(title_frame, text="高效 · 美观 · 鲁棒", 
                font=('Arial', 12), bg='#0d7377', fg='#d4d4d4').pack()
        
        tools_frame = tk.Frame(self.root, bg='#1e1e1e', padx=40, pady=40)
        tools_frame.pack(fill=tk.BOTH, expand=True)
        
        tk.Label(tools_frame, text="可用工具", 
                font=('Arial', 14, 'bold'), bg='#1e1e1e', fg='#d4d4d4').pack(pady=(0, 20))
        
        tool_button_style = {
            'bg': '#14a085',
            'fg': 'white',
            'font': ('Arial', 12, 'bold'),
            'relief': tk.FLAT,
            'padx': 30,
            'pady': 15,
            'cursor': 'hand2',
            'width': 30
        }
        
        tk.Button(tools_frame, text="📷 图片按键分类工具", 
                 command=self.launch_image_classifier, **tool_button_style).pack(pady=10)
        
        info_frame = tk.Frame(self.root, bg='#2b2b2b', padx=10, pady=10)
        info_frame.pack(side=tk.BOTTOM, fill=tk.X)

        tk.Label(info_frame, text="Developer: Gao Rui",
                font=('Arial', 8), bg='#2b2b2b', fg='#808080').pack(side=tk.LEFT)

    def launch_image_classifier(self):
        self.root.destroy()
        config = self.config_manager.get_image_classifier_config()
        classifier = ImageClassifier(config, config_manager=self.config_manager)
        classifier.run()
    
    def run(self):
        self.root.mainloop()


def main():
    app = ARSToolkit()
    app.run()


if __name__ == "__main__":
    main()
