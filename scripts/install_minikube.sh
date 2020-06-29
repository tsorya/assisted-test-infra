#!/bin/bash
export SUDO=$(if [ -x "$(command -v sudo)" ]; then echo "sudo"; else echo ""; fi)

function install_minikube() {
    if ! [ -x "$(command -v minikube)" ]; then
        echo "Installing minikube..."
        curl -Lo minikube https://storage.googleapis.com/minikube/releases/v1.8.2/minikube-linux-amd64
        chmod +x minikube
        ${SUDO} cp minikube /usr/bin/
    else
        echo "minikube is already installed"
    fi
}

function install_kubectl() {
    if ! [ -x "$(command -v kubectl)" ]; then
        echo "Installing kubectl..."
        curl -Lo kubectl https://storage.googleapis.com/kubernetes-release/release/v1.17.0/bin/linux/amd64/kubectl
        chmod +x kubectl
        ${SUDO} mv kubectl /usr/bin/
    else
        echo "kubectl is already installed"
    fi
}

function install_oc() {
    if ! [ -x "$(command -v oc)" ]; then
        echo "Installing oc..."
        curl -Lo oc.tar.gz https://mirror.openshift.com/pub/openshift-v4/clients/oc/${OPENSHIFT_VERSION:-4.5}/linux/oc.tar.gz && ${SUDO} tar -C /usr/local/bin -xf oc.tar.gz && rm -f oc.tar.gz
    else
        echo "oc is already installed"
    fi
}

install_minikube
install_kubectl
install_oc
