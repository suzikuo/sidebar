import base64
import mimetypes
import os


class ImageBase64Converter:
    """
    Logic for converting between images and Base64 strings.
    """

    @staticmethod
    def image_to_base64(file_path: str) -> str:
        """
        Converts an image file to a Base64 string with MIME type prefix.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        mime_type, _ = mimetypes.guess_type(file_path)
        if not mime_type or not mime_type.startswith("image/"):
            # Fallback or strict check? Let's assume user knows what they're doing for now
            mime_type = "image/png"

        with open(file_path, "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
            return f"data:{mime_type};base64,{encoded_string}"

    @staticmethod
    def base64_to_image(base64_str: str, output_path: str) -> str:
        """
        Converts a Base64 string to an image file.
        Returns the output path on success.
        """
        try:
            if "," in base64_str:
                header, base64_str = base64_str.split(",", 1)

            img_data = base64.b64decode(base64_str)

            with open(output_path, "wb") as f:
                f.write(img_data)

            return output_path
        except Exception as e:
            raise ValueError(f"Failed to decode Base64: {e}")
