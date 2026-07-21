import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from PIL import Image, ImageTk
import json
from binding_profiles import DEFAULT_PROFILE_NAME, normalize_binding_profiles
from shortcut_manager import ShortcutManager


class ImageClassifier:
    def __init__(self, config: Dict, config_manager=None):
        self.config = config
        self.config_manager = config_manager
        self.source_folder: Optional[Path] = None
        self.target_folder: Optional[Path] = None
        self.images: List[Path] = []
        self.current_index = 0
        self.key_bindings: Dict[str, str] = {}
        self.binding_profiles: Dict[str, Dict[str, str]] = {}
        self.active_binding_profile = DEFAULT_PROFILE_NAME
        self.profile_var = None
        self.profile_menu = None
        self.classification_active = False
        self.history: List[tuple] = []
        
        self.current_image: Optional[Image.Image] = None
        self.zoom_level = 1.0
        self.pan_offset_x = 0
        self.pan_offset_y = 0
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.is_dragging = False
        self.preserve_zoom = False
        self._is_refreshing = False  # 防止刷新时递归检查

        # 缩放性能优化相关
        self.is_zooming = False
        self.zoom_end_timer = None
        self.zoom_end_delay = self.config.get('zoom_end_delay', 150)  # ms

        self.root = tk.Tk()
        self.root.title("图片分类工具 - ARS")
        self.root.geometry(f"{config.get('window_size', [1200, 800])[0]}x{config.get('window_size', [1200, 800])[1]}")

        # 初始化快捷键管理器
        self.shortcut_manager = ShortcutManager()
        self._init_binding_profiles()
        self._init_shortcuts()

        self.setup_ui()
        
    def setup_ui(self):
        control_frame = tk.Frame(self.root, bg='#2b2b2b', padx=10, pady=10)
        control_frame.pack(side=tk.TOP, fill=tk.X)
        
        btn_style = {'bg': '#0d7377', 'fg': 'white', 'font': ('Arial', 10, 'bold'), 
                     'relief': tk.FLAT, 'padx': 15, 'pady': 8, 'cursor': 'hand2'}
        
        tk.Button(control_frame, text="选择源文件夹", command=self.select_source_folder, **btn_style).pack(side=tk.LEFT, padx=5)
        tk.Button(control_frame, text="修改目标文件夹", command=self.select_target_folder, **btn_style).pack(side=tk.LEFT, padx=5)
        tk.Button(control_frame, text="配置按键绑定", command=self.configure_bindings, **btn_style).pack(side=tk.LEFT, padx=5)
        tk.Button(control_frame, text="开始分类", command=self.start_classification, **btn_style).pack(side=tk.LEFT, padx=5)

        # 分隔符
        tk.Label(control_frame, text="|", bg='#2b2b2b', fg='#555555', font=('Arial', 12)).pack(side=tk.LEFT, padx=10)

        # 文件管理按钮
        file_btn_style = {'bg': '#555555', 'fg': 'white', 'font': ('Arial', 10),
                          'relief': tk.FLAT, 'padx': 12, 'pady': 8, 'cursor': 'hand2'}
        tk.Button(control_frame, text="🔄 刷新", command=self._refresh_file_list, **file_btn_style).pack(side=tk.LEFT, padx=5)
        tk.Button(control_frame, text="📂 打开文件夹", command=self._open_in_explorer, **file_btn_style).pack(side=tk.LEFT, padx=5)

        tk.Label(control_frame, text="跳转:", bg='#2b2b2b', fg='#d4d4d4', font=('Arial', 10)).pack(side=tk.LEFT, padx=(20, 5))
        self.jump_entry = tk.Entry(control_frame, width=8, font=('Arial', 10))
        self.jump_entry.pack(side=tk.LEFT, padx=5)
        self.jump_entry.bind('<FocusIn>', self.on_entry_focus_in)
        self.jump_entry.bind('<FocusOut>', self.on_entry_focus_out)
        tk.Button(control_frame, text="GO", command=self.jump_to_page, bg='#14a085', fg='white', font=('Arial', 10, 'bold'), relief=tk.FLAT, padx=10, pady=8, cursor='hand2').pack(side=tk.LEFT, padx=5)
        self.jump_entry.bind('<Return>', lambda e: self.jump_to_page())
        
        self.preserve_zoom_btn = tk.Button(control_frame, text="🔒 保持缩放", command=self.toggle_preserve_zoom, 
                                           bg='#555555', fg='white', font=('Arial', 9), 
                                           relief=tk.FLAT, padx=12, pady=8, cursor='hand2')
        self.preserve_zoom_btn.pack(side=tk.LEFT, padx=(20, 5))
        self.setup_profile_ui()
        
        info_frame = tk.Frame(self.root, bg='#1e1e1e', padx=10, pady=5)
        info_frame.pack(side=tk.TOP, fill=tk.X)
        
        self.info_label = tk.Label(info_frame, text="请先选择源文件夹（目标文件夹将自动设置为源文件夹的父目录）", 
                                   bg='#1e1e1e', fg='#d4d4d4', font=('Arial', 10))
        self.info_label.pack(side=tk.LEFT)
        
        self.progress_label = tk.Label(info_frame, text="", 
                                       bg='#1e1e1e', fg='#4ec9b0', font=('Arial', 10, 'bold'))
        self.progress_label.pack(side=tk.RIGHT)
        
        self.image_frame = tk.Frame(self.root, bg='#1e1e1e')
        self.image_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        self.canvas = tk.Canvas(self.image_frame, bg='#1e1e1e', highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        self.canvas.bind('<Control-MouseWheel>', self.on_zoom)
        self.canvas.bind('<ButtonPress-1>', self.on_canvas_click)
        self.canvas.bind('<B1-Motion>', self.on_drag_motion)
        self.canvas.bind('<ButtonRelease-1>', self.on_drag_end)
        
        self.image_frame.bind('<Button-1>', lambda e: self.canvas.focus_set())
        self.root.bind('<Button-1>', self.on_root_click)
        
        shortcut_frame = tk.Frame(self.root, bg='#2b2b2b', padx=10, pady=10)
        shortcut_frame.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.shortcut_label = tk.Label(shortcut_frame, text="", 
                                       bg='#2b2b2b', fg='#d4d4d4', 
                                       font=('Arial', 9), justify=tk.LEFT)
        self.shortcut_label.pack(side=tk.LEFT)
        
        self.update_shortcuts_display()

    def setup_profile_ui(self):
        profile_frame = tk.Frame(self.root, bg='#262626', padx=10, pady=6)
        profile_frame.pack(side=tk.TOP, fill=tk.X)

        tk.Label(profile_frame, text="按键方案:", bg='#262626', fg='#d4d4d4',
                 font=('Arial', 10, 'bold')).pack(side=tk.LEFT, padx=(0, 6))

        self.profile_menu = tk.OptionMenu(
            profile_frame,
            self.profile_var,
            *self._profile_names(),
            command=self._select_binding_profile,
        )
        self.profile_menu.config(bg='#3a3a3a', fg='white', font=('Arial', 10),
                                 relief=tk.FLAT, width=18, highlightthickness=0)
        self.profile_menu.pack(side=tk.LEFT, padx=5)

        small_btn_style = {
            'bg': '#555555',
            'fg': 'white',
            'font': ('Arial', 9),
            'relief': tk.FLAT,
            'padx': 10,
            'pady': 4,
            'cursor': 'hand2',
        }
        tk.Button(profile_frame, text="新建方案", command=self.create_binding_profile,
                  **small_btn_style).pack(side=tk.LEFT, padx=5)
        tk.Button(profile_frame, text="删除方案", command=self.delete_binding_profile,
                  **small_btn_style).pack(side=tk.LEFT, padx=5)

    def _init_binding_profiles(self):
        profiles, active_profile, migrated, warnings = normalize_binding_profiles(self.config)
        self.binding_profiles = profiles
        self.active_binding_profile = active_profile
        self.key_bindings = dict(self.binding_profiles.get(active_profile, {}))
        self.profile_var = tk.StringVar(value=self.active_binding_profile)

        if migrated:
            self._save_binding_profiles()

        if warnings:
            self.root.after(100, lambda: messagebox.showwarning("按键方案配置提示", "\n".join(warnings)))

    def _profile_names(self):
        names = list(self.binding_profiles.keys())
        return sorted(names, key=lambda name: (name != DEFAULT_PROFILE_NAME, name.casefold()))

    def _refresh_profile_menu(self):
        if not self.profile_menu:
            return

        menu = self.profile_menu["menu"]
        menu.delete(0, "end")
        for name in self._profile_names():
            menu.add_command(label=name, command=lambda value=name: self._select_binding_profile(value))
        self.profile_var.set(self.active_binding_profile)

    def _save_binding_profiles(self):
        self.config['binding_profiles'] = {
            name: dict(bindings) for name, bindings in self.binding_profiles.items()
        }
        self.config['active_binding_profile'] = self.active_binding_profile
        self.config['default_key_bindings'] = dict(self.key_bindings)
        self._save_config()

    def _select_binding_profile(self, profile_name):
        if profile_name not in self.binding_profiles:
            return

        self.unbind_keys()
        self.active_binding_profile = profile_name
        self.key_bindings = dict(self.binding_profiles[profile_name])
        self.profile_var.set(profile_name)
        self._save_binding_profiles()
        self._refresh_profile_menu()
        self.update_shortcuts_display()

        if self.classification_active:
            self.bind_keys()
        elif self.images:
            self.bind_navigation_only()

    def create_binding_profile(self):
        profile_name = simpledialog.askstring("新建按键方案", "输入方案名称:", parent=self.root)
        if not profile_name:
            return

        profile_name = profile_name.strip()
        if not profile_name:
            messagebox.showwarning("警告", "方案名称不能为空")
            return
        if profile_name in self.binding_profiles:
            messagebox.showwarning("警告", f"按键方案 '{profile_name}' 已存在")
            return

        self.binding_profiles[profile_name] = dict(self.key_bindings)
        self._select_binding_profile(profile_name)
        messagebox.showinfo("成功", f"已创建按键方案: {profile_name}")

    def delete_binding_profile(self):
        if self.active_binding_profile == DEFAULT_PROFILE_NAME:
            messagebox.showwarning("警告", "默认方案不能删除")
            return
        if not messagebox.askyesno("确认删除", f"确定删除按键方案 '{self.active_binding_profile}' 吗?"):
            return

        del self.binding_profiles[self.active_binding_profile]
        self._select_binding_profile(DEFAULT_PROFILE_NAME)
    
    def update_shortcuts_display(self):
        """更新状态栏快捷键显示"""
        # 获取快捷键显示文本
        shortcuts_text = self.shortcut_manager.get_display_text()

        # 分类键显示
        bindings_text = " | ".join([f"{k}: {v}" for k, v in self.key_bindings.items()])

        text = f"快捷键: {shortcuts_text}\n"
        text = f"按键方案: {self.active_binding_profile}\n" + text
        if bindings_text:
            text += f"分类键: {bindings_text}"

        self.shortcut_label.config(text=text)

    def _init_shortcuts(self):
        """初始化快捷键配置，处理迁移和警告"""
        shortcuts_config = self.config.get('shortcuts', {})
        migrated, warnings = self.shortcut_manager.load_from_config(shortcuts_config)

        if migrated:
            # 将迁移后的配置写回 config
            self.config['shortcuts'] = shortcuts_config
            self._save_config()

        if warnings:
            # 延迟显示警告，等待 UI 初始化完成
            self.root.after(100, lambda: self._show_shortcut_warnings(warnings, shortcuts_config))

    def _save_config(self):
        """保存配置到文件"""
        if self.config_manager:
            # 更新 config_manager 中的配置
            for key, value in self.config.items():
                self.config_manager.set(f'image_classifier.{key}', value)
            self.config_manager.save()

    def _show_shortcut_warnings(self, warnings: List[str], shortcuts_config: Dict):
        """显示快捷键配置警告对话框"""
        warning_text = "以下功能未配置快捷键：\n\n"
        warning_text += "\n".join([f"• {w}" for w in warnings])
        warning_text += "\n\n这些功能将不可用。"

        # 创建自定义对话框
        dialog = tk.Toplevel(self.root)
        dialog.title("快捷键配置警告")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg='#2b2b2b')

        # 警告图标和文本
        tk.Label(dialog, text="⚠", font=('Arial', 24), fg='orange', bg='#2b2b2b').pack(pady=(20, 5))
        tk.Label(dialog, text=warning_text, justify=tk.LEFT, padx=20, bg='#2b2b2b', fg='#d4d4d4').pack()

        # 按钮框架
        btn_frame = tk.Frame(dialog, bg='#2b2b2b')
        btn_frame.pack(pady=20)

        def on_continue():
            dialog.destroy()

        def on_restore():
            # 恢复缺失项的默认值
            for action_name, default_keys in ShortcutManager.DEFAULT_SHORTCUTS.items():
                if action_name not in shortcuts_config or not shortcuts_config[action_name].get('keys'):
                    shortcuts_config[action_name] = {"keys": default_keys}

            # 重新加载配置
            self.shortcut_manager.load_from_config(shortcuts_config)
            self.config['shortcuts'] = shortcuts_config
            self._save_config()
            self.update_shortcuts_display()

            dialog.destroy()

        tk.Button(btn_frame, text="继续", command=on_continue, width=10,
                 bg='#555555', fg='white', relief=tk.FLAT).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="恢复默认配置", command=on_restore, width=12,
                 bg='#14a085', fg='white', relief=tk.FLAT).pack(side=tk.LEFT, padx=5)

        # 居中显示
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")

        dialog.wait_window()
    
    def select_source_folder(self):
        folder = filedialog.askdirectory(title="选择包含图片的源文件夹")
        if folder:
            self.source_folder = Path(folder)
            self.target_folder = self.source_folder
            self.scan_images()
            self.update_info()

            # 自动加载预览（不绑定分类键）
            if self.images:
                self.current_index = 0
                self.display_current_image()
                # 绑定导航键用于预览
                self.bind_navigation_only()

            messagebox.showinfo("提示", f"源文件夹: {self.source_folder}\n目标文件夹已自动设置为: {self.target_folder}")
    
    def select_target_folder(self):
        folder = filedialog.askdirectory(title="修改分类后的目标文件夹（可选）")
        if folder:
            self.target_folder = Path(folder)
            self.update_info()
            messagebox.showinfo("提示", f"目标文件夹已修改为: {self.target_folder}")
    
    def scan_images(self):
        if not self.source_folder:
            return
        
        supported_formats = self.config.get('supported_formats', ['.jpg', '.png'])
        images_set = set()
        
        for ext in supported_formats:
            images_set.update(self.source_folder.glob(f"*{ext}"))
            images_set.update(self.source_folder.glob(f"*{ext.upper()}"))
        
        self.images = sorted(list(images_set))
        self.current_index = 0

    def _check_file_exists(self) -> bool:
        """检查当前图片是否存在，不存在则弹窗提示并刷新"""
        # 防止刷新时递归检查
        if self._is_refreshing:
            return True

        if not self.images:
            return False

        if self.current_index >= len(self.images):
            return False

        current_file = self.images[self.current_index]
        if not current_file.exists():
            messagebox.showwarning(
                "文件已变更",
                f"文件已被外部程序修改或删除：\n{current_file.name}\n\n将刷新文件列表。"
            )
            self._refresh_file_list()
            return False
        return True

    def _refresh_file_list(self):
        """重新扫描源文件夹，智能保持当前位置"""
        if not self.source_folder:
            return

        # 设置刷新标志，防止递归检查
        self._is_refreshing = True

        try:
            # 记录当前文件路径
            current_file = None
            if self.images and 0 <= self.current_index < len(self.images):
                current_file = self.images[self.current_index]

            old_count = len(self.images)
            self.scan_images()
            new_count = len(self.images)

            if not self.images:
                self.canvas.delete('all')
                self.progress_label.config(text="")
                self.update_info()
                messagebox.showinfo("刷新完成", "文件夹已清空")
                return

            # 智能定位索引
            if current_file and current_file.exists():
                # 当前文件仍存在，尝试找到它的位置
                try:
                    self.current_index = self.images.index(current_file)
                except ValueError:
                    # 文件被改名或不在列表中，保持在当前索引（不超过边界）
                    self.current_index = min(self.current_index, len(self.images) - 1)
            else:
                # 当前文件被删除，保持索引位置（自动显示下一张）
                self.current_index = min(self.current_index, len(self.images) - 1)

            self.display_current_image()
            self.update_info()
            messagebox.showinfo("刷新完成", f"文件列表已更新\n原: {old_count} 张 → 现: {new_count} 张")
        finally:
            self._is_refreshing = False

    def _open_in_explorer(self):
        """在系统文件管理器中打开当前文件夹"""
        if not self.source_folder:
            messagebox.showwarning("提示", "请先选择源文件夹")
            return

        import subprocess
        import sys

        if sys.platform == 'win32':
            subprocess.run(['explorer', str(self.source_folder)])
        elif sys.platform == 'darwin':  # macOS
            subprocess.run(['open', str(self.source_folder)])
        else:  # Linux
            subprocess.run(['xdg-open', str(self.source_folder)])

    def configure_bindings(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("配置按键绑定")
        dialog.geometry("550x400")
        dialog.configure(bg='#2b2b2b')
        
        tk.Label(dialog, text="按键绑定配置", 
                bg='#2b2b2b', fg='white', font=('Arial', 11, 'bold')).pack(pady=10)
        
        canvas_frame = tk.Frame(dialog, bg='#2b2b2b')
        canvas_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        canvas = tk.Canvas(canvas_frame, bg='#2b2b2b', highlightthickness=0)
        scrollbar = tk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg='#2b2b2b')
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        tk.Label(scrollable_frame, text="按键", bg='#2b2b2b', fg='#d4d4d4', font=('Arial', 9, 'bold')).grid(row=0, column=0, padx=5, pady=5)
        tk.Label(scrollable_frame, text="文件夹名", bg='#2b2b2b', fg='#d4d4d4', font=('Arial', 9, 'bold')).grid(row=0, column=1, padx=5, pady=5)
        tk.Label(scrollable_frame, text="操作", bg='#2b2b2b', fg='#d4d4d4', font=('Arial', 9, 'bold')).grid(row=0, column=2, padx=5, pady=5)
        
        bindings_list = []
        default_bindings = self.config.get('default_key_bindings', {})
        original_bindings = self.key_bindings if self.key_bindings else default_bindings
        current_bindings = dict(original_bindings)
        
        def render_bindings():
            for widget in scrollable_frame.winfo_children():
                if int(widget.grid_info().get('row', 0)) > 0:
                    widget.destroy()
            
            bindings_list.clear()
            for i, (key, folder) in enumerate(current_bindings.items()):
                bindings_list.append((key, folder))
            
            for i, (key, folder) in enumerate(bindings_list):
                row = i + 1
                
                key_entry = tk.Entry(scrollable_frame, width=8, font=('Arial', 10))
                key_entry.insert(0, key)
                key_entry.grid(row=row, column=0, padx=5, pady=3)
                
                folder_entry = tk.Entry(scrollable_frame, width=20, font=('Arial', 10))
                folder_entry.insert(0, folder)
                folder_entry.grid(row=row, column=1, padx=5, pady=3)
                
                def make_delete_handler(idx):
                    return lambda: delete_binding(idx)
                
                delete_btn = tk.Button(scrollable_frame, text="删除", 
                                      command=make_delete_handler(i),
                                      bg='#d9534f', fg='white', font=('Arial', 8),
                                      relief=tk.FLAT, padx=8, pady=3, cursor='hand2')
                delete_btn.grid(row=row, column=2, padx=5, pady=3)
                
                bindings_list[i] = (key_entry, folder_entry)
        
        def delete_binding(index):
            if 0 <= index < len(bindings_list):
                key_entry, folder_entry = bindings_list[index]
                old_key = key_entry.get()
                if old_key in current_bindings:
                    del current_bindings[old_key]
                render_bindings()
        
        def add_binding():
            key = simpledialog.askstring("添加绑定", "输入按键 (单个字符):", parent=dialog)
            if key and len(key) == 1:
                if key in current_bindings:
                    messagebox.showwarning("警告", f"按键 '{key}' 已存在", parent=dialog)
                    return
                folder = simpledialog.askstring("添加绑定", f"输入按键 '{key}' 对应的文件夹名:", parent=dialog)
                if folder:
                    current_bindings[key] = folder
                    render_bindings()
        
        def save_bindings():
            new_bindings = {}
            for key_entry, folder_entry in bindings_list:
                key = key_entry.get().strip()
                folder = folder_entry.get().strip()
                if key and folder:
                    if len(key) != 1:
                        messagebox.showerror("错误", f"按键必须是单个字符: '{key}'", parent=dialog)
                        return
                    if key in new_bindings:
                        messagebox.showerror("错误", f"按键 '{key}' 重复", parent=dialog)
                        return
                    new_bindings[key] = folder
            
            self.key_bindings = new_bindings
            self.binding_profiles[self.active_binding_profile] = dict(new_bindings)
            self._save_binding_profiles()
            self.update_shortcuts_display()
            if self.classification_active:
                self.bind_keys()

            # 注意：保存按键绑定不会自动进入分类模式
            # 用户需要点击"开始分类"才能开始操作

            dialog.destroy()
            messagebox.showinfo("成功", f"已保存 {len(new_bindings)} 个按键绑定")
        
        render_bindings()
        
        btn_frame = tk.Frame(dialog, bg='#2b2b2b')
        btn_frame.pack(pady=10)
        
        tk.Button(btn_frame, text="添加绑定", command=add_binding, 
                 bg='#0d7377', fg='white', padx=10, pady=5).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="保存", command=save_bindings, 
                 bg='#14a085', fg='white', padx=20, pady=5).pack(side=tk.LEFT, padx=5)
    
    def update_info(self):
        info_parts = []
        if self.source_folder:
            info_parts.append(f"源: {self.source_folder} ({len(self.images)} 张图片)")
        if self.target_folder:
            info_parts.append(f"目标: {self.target_folder}")

        self.info_label.config(text=" | ".join(info_parts) if info_parts else "请选择文件夹")
    
    def start_classification(self):
        if not self.source_folder or not self.target_folder:
            messagebox.showerror("错误", "请先选择源文件夹和目标文件夹")
            return
        
        if not self.images:
            messagebox.showwarning("警告", "源文件夹中没有找到图片")
            return
        
        if not self.key_bindings:
            self.key_bindings = dict(self.binding_profiles.get(self.active_binding_profile, {}))

        # 文件夹将在按下分类键时按需创建（在 classify_image 中处理）

        # 保持当前位置，不重置到第一张
        self.canvas.focus_set()
        self.display_current_image()
        self.classification_active = True
        self.bind_keys()
    
    def display_current_image(self):
        if not self.images:
            messagebox.showinfo("完成", "所有图片已处理完毕!")
            self.unbind_keys()
            self.classification_active = False
            self.canvas.delete('all')
            return

        # 取消之前的缩放定时器，避免导航时触发额外渲染
        if self.zoom_end_timer:
            self.root.after_cancel(self.zoom_end_timer)
            self.zoom_end_timer = None

        if self.current_index >= len(self.images):
            self.current_index = len(self.images) - 1

        if self.current_index < 0:
            self.current_index = 0

        # 检查文件是否存在
        if not self._check_file_exists():
            return

        current_image_path = self.images[self.current_index]

        try:
            self.current_image = Image.open(current_image_path)
            
            if not self.preserve_zoom:
                self.zoom_level = 1.0
                self.pan_offset_x = 0
                self.pan_offset_y = 0
            
            self.render_image()
            
            self.canvas.focus_set()
            
            self.progress_label.config(text=f"{self.current_index + 1} / {len(self.images)}")
            self.root.title(f"图片分类工具 - {current_image_path.name}")
            
        except Exception as e:
            messagebox.showerror("错误", f"无法加载图片: {e}")
            self.next_image()
    
    def render_image(self, use_fast=False):
        if not self.current_image:
            return

        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()

        if canvas_width <= 1 or canvas_height <= 1:
            canvas_width, canvas_height = 1000, 600

        img = self.current_image.copy()
        img_width, img_height = img.size

        scale = min(canvas_width / img_width, canvas_height / img_height)
        self.base_scale = scale

        final_scale = scale * self.zoom_level
        new_width = int(img_width * final_scale)
        new_height = int(img_height * final_scale)

        if new_width > 0 and new_height > 0:
            # 缩放过程中使用 BILINEAR（快），结束后使用 LANCZOS（高质量）
            resampling = Image.Resampling.BILINEAR if use_fast else Image.Resampling.LANCZOS
            img = img.resize((new_width, new_height), resampling)

        self.photo = ImageTk.PhotoImage(img)

        self.canvas.delete('all')

        x = canvas_width // 2 + self.pan_offset_x
        y = canvas_height // 2 + self.pan_offset_y

        self.canvas.create_image(x, y, image=self.photo, anchor=tk.CENTER)
    
    def on_zoom(self, event):
        if not self.current_image:
            return

        # 标记正在缩放
        self.is_zooming = True

        # 取消之前的结束定时器
        if self.zoom_end_timer:
            self.root.after_cancel(self.zoom_end_timer)
            self.zoom_end_timer = None

        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()

        mouse_x = event.x
        mouse_y = event.y

        center_x = canvas_width // 2 + self.pan_offset_x
        center_y = canvas_height // 2 + self.pan_offset_y

        offset_x = mouse_x - center_x
        offset_y = mouse_y - center_y

        old_zoom = self.zoom_level

        if event.delta > 0:
            self.zoom_level *= 1.1
        else:
            self.zoom_level /= 1.1

        self.zoom_level = max(0.1, min(self.zoom_level, 10.0))

        zoom_ratio = self.zoom_level / old_zoom

        self.pan_offset_x -= offset_x * (zoom_ratio - 1)
        self.pan_offset_y -= offset_y * (zoom_ratio - 1)

        # 使用快速渲染
        self.render_image(use_fast=True)

        # 设置延迟后进行高质量渲染
        self.zoom_end_timer = self.root.after(self.zoom_end_delay, self.on_zoom_end)

    def on_zoom_end(self):
        """缩放结束后进行高质量渲染"""
        self.is_zooming = False
        self.zoom_end_timer = None
        if self.current_image:
            self.render_image(use_fast=False)
    
    def on_canvas_click(self, event):
        self.canvas.focus_set()
        self.on_drag_start(event)
    
    def on_root_click(self, event):
        widget = event.widget
        if widget != self.jump_entry and not str(widget).startswith(str(self.jump_entry)):
            self.canvas.focus_set()
    
    def on_drag_start(self, event):
        self.is_dragging = True
        self.drag_start_x = event.x
        self.drag_start_y = event.y
        self.canvas.config(cursor='fleur')
    
    def on_drag_motion(self, event):
        if self.is_dragging:
            dx = event.x - self.drag_start_x
            dy = event.y - self.drag_start_y
            
            self.pan_offset_x += dx
            self.pan_offset_y += dy
            
            self.drag_start_x = event.x
            self.drag_start_y = event.y
            
            self.render_image()
    
    def on_drag_end(self, event):
        self.is_dragging = False
        self.canvas.config(cursor='')

    def bind_navigation_only(self):
        """仅绑定导航键，用于预览模式"""
        self.unbind_keys()

        callbacks = {
            'next': self.next_image,
            'previous': self.previous_image,
            'skip': self.next_image,
            'refresh': self._refresh_file_list,
            'open_folder': self._open_in_explorer,
        }
        self.shortcut_manager.bind_all(self.root, callbacks)

    def bind_keys(self):
        """绑定所有快捷键，用于分类模式"""
        self.unbind_keys()

        callbacks = {
            'next': self.next_image,
            'previous': self.previous_image,
            'skip': self.next_image,
            'undo': self.undo_last_action,
            'refresh': self._refresh_file_list,
            'open_folder': self._open_in_explorer,
            'exit': self.quit_classification,
        }
        self.shortcut_manager.bind_all(self.root, callbacks)

        # 绑定分类键
        for key in self.key_bindings.keys():
            self.root.bind(f"<{key}>", lambda e, k=key: self.classify_image(k))

    def unbind_keys(self):
        """解绑所有快捷键"""
        self.shortcut_manager.unbind_all(self.root)

        # 解绑分类键
        for key in self.key_bindings.keys():
            try:
                self.root.unbind(f"<{key}>")
            except tk.TclError:
                pass
    
    def classify_image(self, key: str):
        if key not in self.key_bindings:
            return

        if not self.images or self.current_index >= len(self.images):
            return

        # 检查文件是否存在
        if not self._check_file_exists():
            return

        source_path = self.images[self.current_index]
        folder_name = self.key_bindings[key]
        target_folder_path = self.target_folder / folder_name
        
        target_folder_path.mkdir(parents=True, exist_ok=True)
        
        target_path = target_folder_path / source_path.name
        
        counter = 1
        while target_path.exists():
            stem = source_path.stem
            suffix = source_path.suffix
            target_path = target_folder_path / f"{stem}_{counter}{suffix}"
            counter += 1
        
        try:
            shutil.move(str(source_path), str(target_path))
            self.history.append(('move', source_path, target_path))
            self.images.pop(self.current_index)
            
            if self.current_index >= len(self.images) and len(self.images) > 0:
                self.current_index = len(self.images) - 1
            
            self.display_current_image()
        except Exception as e:
            messagebox.showerror("错误", f"移动文件失败: {e}")
    
    def next_image(self):
        if self.images and self.current_index < len(self.images) - 1:
            self.current_index += 1
            self.display_current_image()
        elif not self.images:
            messagebox.showinfo("提示", "没有图片可显示")
    
    def previous_image(self):
        if self.images and self.current_index > 0:
            self.current_index -= 1
            self.display_current_image()
        elif not self.images:
            messagebox.showinfo("提示", "没有图片可显示")
    
    def toggle_preserve_zoom(self):
        self.preserve_zoom = not self.preserve_zoom
        if self.preserve_zoom:
            self.preserve_zoom_btn.config(bg='#14a085', text='🔒 保持缩放 ✓')
        else:
            self.preserve_zoom_btn.config(bg='#555555', text='🔒 保持缩放')
    
    def on_entry_focus_in(self, event):
        self.unbind_keys()
    
    def on_entry_focus_out(self, event):
        if self.images:
            self.bind_keys()
    
    def jump_to_page(self):
        if not self.images:
            messagebox.showwarning("警告", "请先开始分类")
            return
        
        try:
            page_num = int(self.jump_entry.get())
            if 1 <= page_num <= len(self.images):
                self.current_index = page_num - 1
                self.display_current_image()
                self.jump_entry.delete(0, tk.END)
                self.canvas.focus_set()
            else:
                messagebox.showerror("错误", f"页码必须在 1 到 {len(self.images)} 之间")
        except ValueError:
            messagebox.showerror("错误", "请输入有效的数字")
    
    def undo_last_action(self):
        if not self.history:
            messagebox.showinfo("提示", "没有可撤销的操作")
            return
        
        action, source, target = self.history.pop()
        if action == 'move':
            try:
                shutil.move(str(target), str(source))
                self.images.insert(self.current_index, source)
                self.display_current_image()
            except Exception as e:
                messagebox.showerror("错误", f"撤销失败: {e}")
    
    def quit_classification(self):
        if messagebox.askyesno("确认", "确定要退出分类吗？"):
            self.unbind_keys()
            # 保持当前位置，不重置到第一张
            # 退出分类模式后恢复预览模式（可浏览但不可操作）
            self.classification_active = False
            if self.images:
                self.bind_navigation_only()
    
    def run(self):
        self.root.mainloop()
