FROM alpine

WORKDIR /usr/src/app

COPY ./Dockerfile ./dispatcher.py ./worker.py ./qstat.py ./requirements.txt ./

RUN adduser --disabled-password appuser && \
    apk add --no-cache python3 py3-pip py3-requests libmagic logger \
    # Additional packages could be plugged in here
    # build-base gnuplot curl git && \
    && \
    pip3 install -r requirements.txt && \
    rm -fr /root/.cache

USER appuser

CMD ["./worker.py"]
