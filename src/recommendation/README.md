# Recommendation Service

This service provides recommendations for other products based on the currently
selected product.

# Upgrade the pip and then install all the project dependencies
pip install --upgrade pip

pip install -r requirements.txt

# To run the python file
> python recommendation_server.py

## Local Build

To build the protos, run from the root directory:

```sh
make docker-generate-protobuf
```

## Docker Build

From the root directory, run:

```sh
docker compose build recommendation
```
