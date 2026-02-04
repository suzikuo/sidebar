from core.ui_kernel.design_tokens import DesignTokens


class ThemeEngine:
    """
    Transforms design tokens into QSS (Qt Style Sheets).
    Modern theme with gradients, glassmorphism, and smooth animations.
    """

    def __init__(self, tokens: DesignTokens):
        self.tokens = tokens
        self.theme_mode = "dark"  # 'light', 'dark', 'system'
        self.font_family = "Segoe UI"
        self.font_size = 13
        self.accent_color = "#FF6B9D"

    def set_theme_mode(self, mode: str):
        """Set theme mode (light/dark/system)."""
        self.theme_mode = mode
        if mode == "light":
            self.tokens.DEFAULT_TOKENS["colors"]["sidebar_bg"] = "#F5F5F5"
            self.tokens.DEFAULT_TOKENS["colors"]["sidebar_icon"] = "#333333"
        elif mode == "dark":
            self.tokens.DEFAULT_TOKENS["colors"]["sidebar_bg"] = "#1a1a2e"
            self.tokens.DEFAULT_TOKENS["colors"]["sidebar_icon"] = "#FFFFFF"

    def set_font(self, family: str = None, size: int = None):
        """Set application font."""
        if family:
            self.font_family = family
        if size:
            self.font_size = size

    def set_accent_color(self, color: str):
        """Set accent color."""
        self.accent_color = color

    def get_base_qss(self) -> str:
        """
        Generates custom QSS.
        Note: qfluentwidgets handles most styling automatically.
        We only add specific overrides here if absolutely necessary.
        """
        return """
            /* Global Overrides if needed - currently keeping it clean for Fluent Design */
            /* All components should use their native Fluent styles */
        """

    def get_component_qss(self, component_name: str) -> str:
        """Returns QSS for specific custom components."""
        if component_name == "PluginCard":
            return """
                #PluginCard {
                    background: qlineargradient(
                        x1:0, y1:0, x2:0, y2:1,
                        stop:0 rgba(255, 255, 255, 0.08),
                        stop:1 rgba(255, 255, 255, 0.03)
                    );
                    border: 2px solid rgba(255, 255, 255, 0.1);
                    border-radius: 12px;
                    padding: 16px;
                }
                
                #PluginCard:hover {
                    border: 2px solid rgba(255, 107, 157, 0.5);
                    background: qlineargradient(
                        x1:0, y1:0, x2:0, y2:1,
                        stop:0 rgba(255, 255, 255, 0.12),
                        stop:1 rgba(255, 255, 255, 0.05)
                    );
                }
            """
        return ""

    def reload_theme(self):
        """Reload theme - to be called after settings changes."""
        pass
