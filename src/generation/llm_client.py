"""OpenAI LLM client for the RAG generation pipeline."""

import os

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()


class LLMClient:
    """Client responsible for communicating with the configured LLM."""

    def __init__(self, model="gpt-5-nano"):
        self.model = model

        api_key = os.getenv("OPENAI_API_KEY")

        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY is not set. "
                "Add it to the project's .env file."
            )

        self.client = OpenAI(api_key=api_key)

    def generate(self, prompt):
        """Generate a response from the configured LLM."""

        response = self.client.responses.create(
            model=self.model,
            input=prompt,
            reasoning={
                "effort": "low",
            },
            max_output_tokens=2000,
        )

        return response.output_text
    