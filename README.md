## grpc-gateway-generator

Build and Push automatically grpc-gateway.

## Usage

- `folders`: A list of folders (relative to your repository) separated with spaces
- `docker-username` and `docker-password`: Docker credentials (TODO: allow custom registry) 
- `docker-repository`: The repository where the image will be pushed.


````yaml
on: [push]

jobs:
  grpc_gateway:
    runs-on: ubuntu-latest
    name: testing compiling
    steps:
      - uses: actions/checkout@v3
        with:
          fetch-depth: 2
      - name: grpc-gateway-action
        uses: axel7083/grpc-gateway-generator@v1.0
        with:
          repo-token: ${{ secrets.GITHUB_TOKEN }}
          folders: ./protos/service.a /protos/service.b
          docker-username: ${{ secrets.DOCKERHUB_USERNAME }}
          docker-password: ${{ secrets.DOCKERHUB_TOKEN }}
          docker-repository: axel7083/dev
````

## Images

This action will publish one image per folder provided. The images will be named as followed `{docker-repository}:grpc-gateway-{folder}-{timestamp}`. Using the previous config we can get the following images
- `axel7083/dev:grpc-gateway-service-a-1674593599`
- `axel7083/dev:grpc-gateway-service-b-1674593599`
