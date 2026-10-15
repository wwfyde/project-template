import base64
from pathlib import Path

from api.core import settings
from google import genai
from PIL import Image

provider = settings.providers.google
if not provider:
    raise ValueError("Provider not provided")
api_key = provider.api_key.get_secret_value()
client = genai.Client(api_key=api_key)


def main() -> list[Path]:
    interaction = client.interactions.create(
        model="gemini-3.1-flash-image-preview",
        input="Create a picture of a nano banana dish in a fancy restaurant with a Gemini theme",
        # response_format={"image": {"aspect_ratio": "5:4", "image_size": "1K"}},
    )
    files = []
    for step in interaction.steps:
        if step.type == "model_output":
            for i, content_block in enumerate(step.content):
                if content_block.type == "text":
                    print(content_block.text)
                elif content_block.type == "image":
                    file = f"generated_image_{i}.png"
                    with open(file, "wb") as f:
                        f.write(base64.b64decode(content_block.data))
                        files.append(Path(file))

    return files


if __name__ == "__main__":
    print("a")
    main()
