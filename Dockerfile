FROM python:3.9

WORKDIR /code

COPY ./requirements.txt /code/requirements.txt
COPY ./pyproject.toml /code/pyproject.toml

RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt
RUN pip install poetry

RUN poetry install

COPY ./main.py /code/

VOLUME /paligo

#CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80", "--reload"]
CMD ["/bin/bash"]