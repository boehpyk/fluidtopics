docker run -d --name fluidtopics -p 8989:80 -v $(pwd):/code fluidtopics
uvicorn main:app --host 0.0.0.0 --port 80 --reload