import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
)
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QPixmap, QDesktopServices

class WelcomeWidget(QWidget):
    """
    The Welcome Screen Widget.
    Provides entry points to Create or Import a project.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("welcome_page") 
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(20)
        
        # --- 1. Title & Logo ---
        title_layout = QHBoxLayout()
        title_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        title_layout.setSpacing(15) 
        
        title = QLabel("Video Annotation Tool")
        title.setObjectName("welcome_title_lbl")
        
        self.logo_lbl = QLabel()
        
        current_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.dirname(os.path.dirname(current_dir))
        logo_path = os.path.join(root_dir, "image", "logo.png")
        
        pixmap = QPixmap(logo_path)
        if not pixmap.isNull():
            scaled_pixmap = pixmap.scaledToHeight(40, Qt.TransformationMode.SmoothTransformation)
            self.logo_lbl.setPixmap(scaled_pixmap)
        else:
            self.logo_lbl.setText("(Logo missing)") 
            
        title_layout.addWidget(title)
        title_layout.addWidget(self.logo_lbl)
        
        layout.addLayout(title_layout)
        
        # --- 2. Primary Actions (Vertical) ---
        self.create_btn = QPushButton("Create New Project")
        self.create_btn.setFixedSize(200, 50)
        self.create_btn.setProperty("class", "welcome_action_btn")
        self.create_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        
        self.import_btn = QPushButton("Import Project JSON")
        self.import_btn.setFixedSize(200, 50)
        self.import_btn.setProperty("class", "welcome_action_btn")
        self.import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        
        layout.addWidget(self.create_btn, alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.import_btn, alignment=Qt.AlignmentFlag.AlignHCenter)

        layout.addSpacing(15)

        # --- 3. Secondary Actions (Horizontal) ---
        links_layout = QHBoxLayout()
        links_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        links_layout.setSpacing(20) 

        self.tutorial_btn = QPushButton("📺 Video Tutorial")
        self.tutorial_btn.setFixedSize(160, 40) 
        self.tutorial_btn.setProperty("class", "welcome_secondary_btn") 
        self.tutorial_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tutorial_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://drive.google.com/file/d/1EgQXGMQya06vNMuX_7-OlAUjF_Je-ye_/view?usp=sharing")))

        self.github_btn = QPushButton("🐙 GitHub Repo")
        self.github_btn.setFixedSize(160, 40)
        self.github_btn.setProperty("class", "welcome_secondary_btn")
        self.github_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.github_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/OpenSportsLab/soccernetpro-ui/tree/dev-jintao")))

        links_layout.addWidget(self.tutorial_btn)
        links_layout.addWidget(self.github_btn)

        layout.addLayout(links_layout)
