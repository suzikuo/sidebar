import os
import random


class ThiefBookReader:
    def __init__(self):
        self.txt_path = ""
        self.current_page = 1
        self.page_length = 50
        self.is_english = False
        self.line_break = " "
        self._content = ""
        self._pages = []
        self._is_boss_key_active = False
        self._boss_key_texts = [
            'print("Hello World")',
            'console.log("Hello World");',
            'System.out.println("Hello World");',
            'fmt.Println("Hello World")',
            'echo "Hello World"',
            'printf("Hello World\\n");',
            'std::cout << "Hello World" << std::endl;',
        ]

    def update_config(self, config: dict):
        """Update configurations and reload if pathway changed."""
        old_path = self.txt_path
        old_length = self.page_length
        old_english = self.is_english

        self.txt_path = config.get("txt_path", "")
        self.current_page = config.get("current_page", 1)
        self.page_length = config.get("page_length", 50)
        self.is_english = config.get("is_english", False)
        self.line_break = config.get("line_break", " ")
        if self.line_break == "":
            self.line_break = " "

        # Reload if path or pagination parameters changed
        if (
            (self.txt_path != old_path)
            or (self.page_length != old_length)
            or (self.is_english != old_english)
        ):
            self.load_file()
            # Boundary check for current_page after reloading
            self._ensure_page_bounds()

    def load_file(self):
        """Read the TXT file into memory and paginate it."""
        self._content = ""
        self._pages = []
        if not self.txt_path or not os.path.exists(self.txt_path):
            return

        # Try multiple encodings
        encodings = ["utf-8", "gbk", "gb2312", "utf-16"]
        for enc in encodings:
            try:
                with open(self.txt_path, "r", encoding=enc) as f:
                    self._content = f.read()
                break
            except UnicodeDecodeError:
                continue

        # Clean content and standardize newlines
        self._content = self._content.replace("\r\n", "\n").replace("\r", "\n")
        # Remove consecutive empty lines if needed, or just split by length
        self._paginate()

    def _paginate(self):
        """Split content into pages based on page_length."""
        self._pages = []
        if not self._content:
            return

        idx = 0
        total_len = len(self._content)

        # Simple pagination: chunks of size `page_length`
        # In English, we might want to split by words instead of raw character count if is_english is True,
        # but to keep it simple and consistent with standard ThiefBook, we can split by chars but avoid breaking words.
        while idx < total_len:
            if self.is_english:
                # Find the next space after idx + page_length
                end_idx = idx + self.page_length
                if end_idx >= total_len:
                    self._pages.append(
                        self._content[idx:].replace("\n", self.line_break)
                    )
                    break

                # Try to not break a word
                while end_idx < total_len and not self._content[end_idx].isspace():
                    end_idx += 1

                chunk = self._content[idx:end_idx].strip()
                if chunk:
                    self._pages.append(chunk.replace("\n", self.line_break))
                idx = end_idx + 1
            else:
                chunk = self._content[idx : idx + self.page_length].strip()
                if chunk:
                    self._pages.append(chunk.replace("\n", self.line_break))
                idx += self.page_length

    def _ensure_page_bounds(self):
        if not self._pages:
            self.current_page = 1
        else:
            if self.current_page < 1:
                self.current_page = 1
            if self.current_page > len(self._pages):
                self.current_page = len(self._pages)

    def get_current_text(self) -> str:
        """Returns the text for the current page, or Boss Key text, or an error/prompt."""
        if self._is_boss_key_active:
            return random.choice(self._boss_key_texts)

        if not self.txt_path:
            return "无歌词"
        if not os.path.exists(self.txt_path):
            return "歌词不存在,请检查路径"
        if not self._pages:
            return "歌词为空或读取失败"

        if 1 <= self.current_page <= len(self._pages):
            return self._pages[self.current_page - 1]
        return "没有更多内容了"

    def next_page(self) -> bool:
        """Goes to next page. Returns True if page changed."""
        if self._is_boss_key_active:
            self._is_boss_key_active = False
            return True

        if self._pages and self.current_page < len(self._pages):
            self.current_page += 1
            return True
        return False

    def prev_page(self) -> bool:
        """Goes to previous page. Returns True if page changed."""
        if self._is_boss_key_active:
            self._is_boss_key_active = False
            return True

        if self._pages and self.current_page > 1:
            self.current_page -= 1
            return True
        return False

    def jump_to(self, page: int) -> bool:
        """Jumps to a specific page. Returns True if changed."""
        if self._is_boss_key_active:
            self._is_boss_key_active = False

        old_page = self.current_page
        self.current_page = page
        self._ensure_page_bounds()
        return old_page != self.current_page

    def toggle_boss_key(self):
        """Toggles the boss key mode."""
        self._is_boss_key_active = not self._is_boss_key_active
        return True

    def search_keyword(self, keyword: str) -> bool:
        """
        Searches for the keyword starting from the next page.
        If found, sets current_page to that page and returns True.
        If not found, returns False.
        """
        if not self._pages or not keyword:
            return False

        if self._is_boss_key_active:
            self._is_boss_key_active = False

        start_idx = self.current_page  # current_page is 1-indexed, so this is the index of the next page

        # Search from next page to end
        for i in range(start_idx, len(self._pages)):
            if keyword in self._pages[i]:
                self.current_page = i + 1
                return True

        # Wrap around from beginning to current page
        for i in range(0, start_idx):
            if keyword in self._pages[i]:
                self.current_page = i + 1
                return True

        return False
