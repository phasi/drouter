FROM alpine:3.10

RUN apk update && apk add python3

COPY src /drouter
WORKDIR /drouter

CMD [ "python3", "drouter.py" ]