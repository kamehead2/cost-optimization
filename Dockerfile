FROM registry.access.redhat.com/ubi9/python-312:latest

RUN pip install --upgrade pip && pip --version && \
    pip install ibm-vpc ibm-cloud-sdk-core ibm-platform-services

WORKDIR /opt/app-root/src

COPY ibmc-muda-vols-check.py ./

CMD ["python", "-u", "./ibmc-muda-vols-check.py"]