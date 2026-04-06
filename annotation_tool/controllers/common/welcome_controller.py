from PyQt6.QtCore import QObject, QUrl
from PyQt6.QtGui import QDesktopServices


class WelcomeController(QObject):
    """
    Controller for WelcomeWidget actions.
    Owns routing and external link behavior.
    """

    TUTORIAL_URL = "https://www.youtube.com/"
    GITHUB_URL = "https://github.com/OpenSportsLab/VideoAnnotationTool"

    def __init__(self, panel, router, parent=None):
        super().__init__(parent)
        self.panel = panel
        self.router = router
        self._setup_connections()
        self.refresh_recent_projects()

    def _setup_connections(self):
        self.panel.createProjectRequested.connect(self.router.create_new_project_flow)
        self.panel.importProjectRequested.connect(self.router.import_annotations)
        self.panel.tutorialRequested.connect(self._open_tutorial)
        self.panel.githubRequested.connect(self._open_github)
        self.panel.recentProjectRequested.connect(self._open_recent_project)
        self.panel.recentProjectRemoveRequested.connect(self._remove_recent_project)

    def _open_tutorial(self):
        QDesktopServices.openUrl(QUrl(self.TUTORIAL_URL))

    def _open_github(self):
        QDesktopServices.openUrl(QUrl(self.GITHUB_URL))

    def _open_recent_project(self, path: str):
        self.router.open_project_from_path(path)
        self.refresh_recent_projects()

    def _remove_recent_project(self, path: str):
        self.router.remove_recent_project(path)
        self.refresh_recent_projects()

    def refresh_recent_projects(self):
        self.panel.set_recent_projects(self.router.get_recent_projects())
