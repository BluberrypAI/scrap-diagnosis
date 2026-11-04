import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run("wastecalc.web.app:app", host="127.0.0.1", port=int(os.getenv("PORT", "8000")))
