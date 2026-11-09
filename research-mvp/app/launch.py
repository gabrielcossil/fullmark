"""Start only a closed setup page until required production secrets exist."""

import os
import uvicorn
from .config import settings


def main():
    try:
        settings()
        target = "app.main:app"
    except RuntimeError:
        target = "app.setup:app"
    uvicorn.run(target, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))


if __name__ == "__main__":
    main()
