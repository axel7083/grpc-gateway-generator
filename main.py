import logging

import time
import git
import tempfile
import argparse
from pathlib import Path
from os import path, remove
from glob import glob
import shutil
import subprocess
import re
from string import Template
import docker
from docker import DockerClient
from docker.errors import APIError


def create_logger(name: str):
    logger = logging.getLogger(name)

    logger.setLevel(logging.INFO)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)

    formatter = logging.Formatter('[%(threadName)s] %(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    return logger


def get_protos(directory: str) -> [str]:
    return glob(path.join(directory, "*.proto"))


def create_services_code(services: [str]) -> str:
    output = ""
    for i, service in enumerate(services):

        if i == 0:
            output = 'err := gw.'
        else:
            output = output + '\n	err = gw.'

        output = output + (service + '(ctx,mux,*flag.String("' + service.lower() + '",grpcEndpoint, "gRPC server endpoint"), opts)')

    return output


def where_am_i() -> Path:
    return Path(__file__).resolve().parent


class GrpcGatewayBuilder:

    def __init__(self,
                 repository_folder: str,
                 docker_repository: str,
                 prefix_tag: str = "grpc-gateway-",
                 always_rebuild: bool = False
                 ) -> None:
        self.logger = create_logger(GrpcGatewayBuilder.__name__)
        self.docker_client: DockerClient = docker.from_env()
        self.repository_folder = repository_folder
        self.docker_repository = docker_repository
        self.prefix_tag = prefix_tag
        self.git_repo = git.Repo(repository_folder)
        self.always_rebuild = always_rebuild
        # Create a temporary folder
        self.temp_directory = tempfile.TemporaryDirectory()

        self.execution_dir = where_am_i()

    def docker_image_exist(self, image: str) -> bool:
        try:
            self.docker_client.api.inspect_distribution(image)
            return True
        except APIError:
            return False

    def folder_has_diff(self, folder):
        if folder.startswith("/"):
            folder = folder[1:]

        head = str(self.git_repo.commit("HEAD"))
        head_1 = str(self.git_repo.commit("HEAD~1"))
        return len(self.git_repo.git.diff(head, head_1, folder)) > 0

    def generate_go(self, _id: str, protos: [str]):
        self.logger.info(f"Generating go for {_id}.")
        # Fetch all the files in the template dir
        template = glob(path.join(self.execution_dir, "template", "*"))

        output = path.join(self.temp_directory.name, _id)
        dest = path.join(output, "template")
        Path(dest).mkdir(parents=True, exist_ok=True)

        shutil.copyfile(path.join(self.execution_dir, "Dockerfile"), path.join(output, "Dockerfile"))

        for file in template:
            shutil.copyfile(file, path.join(dest, path.basename(file)))

        for proto in protos:
            shutil.copyfile(proto, path.join(dest, path.basename(proto)))

        p = subprocess.run(["buf", "generate"], cwd=dest, capture_output=True)

        if p.returncode != 0:
            print('exit status:', p.returncode)
            print('stdout:', p.stdout.decode())
            print('stderr:', p.stderr.decode())
            raise Exception("Could not generate grpc-gateway.")

        protos_definitions = glob(path.join(dest, "gen", "go", "*.pb.gw.go"))

        services = []
        for definition in protos_definitions:
            with open(definition, "r") as def_file:
                content = def_file.read()
                _services = re.findall(r'Register\w+HandlerFromEndpoint', content)
                if len(_services) > 0:
                    services.extend(_services)

        services = list(set(services))

        template_path = path.join(dest, "main.go.template")
        with open(template_path, "r", encoding="utf-8") as main_go_template:
            content = Template(main_go_template.read())
            output = content.substitute(services=create_services_code(services))

            with open(path.join(dest, "main.go"), "w", encoding="utf-8") as main_go:
                main_go.write(output)

        remove(template_path)

    def build_docker_image(self, build_dir: str, partial_tag: str, latest_tag: str):
        self.logger.info(f"Building docker in directory {build_dir}.")
        timestamped_tag = f"{partial_tag}-{str(int(time.time()))}"
        full_image = f"{self.docker_repository}:{timestamped_tag}"
        image, _ = self.docker_client.images.build(
            path=build_dir,
            dockerfile="Dockerfile",
            buildargs={"project": "template"},
            tag=full_image
        )

        self.docker_client.images.push(repository=self.docker_repository, tag=timestamped_tag)
        self.docker_client.api.tag(image=full_image, repository=self.docker_repository, tag=latest_tag)

    def start(self, folders: [str]):
        self.logger.info(f"Starting analysing {len(folders)} folder(s).")
        for folder in folders:
            # Get the absolute path and ensure it exists
            absolute_path = path.join(self.repository_folder, folder)
            if not Path(absolute_path).exists():
                raise Exception("The folder " + folder + " does not exist in the repository given.")

            # Get all the protos files inside the given folder
            protos = get_protos(absolute_path)
            if len(protos) == 0:
                raise Exception("The folder given do not have any .proto files.")

            # The id used will be the directory name where the proto files are located
            _id = folder[len(path.dirname(folder)) + 1:]

            partial_tag = f"{self.prefix_tag}-{_id}"
            latest_tag = f"{partial_tag}-latest"

            # If we never built the images OR the folder has changed since the last commit.
            if self.always_rebuild \
                    or not self.docker_image_exist(f"{self.docker_repository}:{latest_tag}") \
                    or self.folder_has_diff(folder):
                self.logger.info(f"Folder {folder} will be build and push.")
                self.generate_go(_id, protos)
                self.build_docker_image(
                    build_dir= path.join(self.temp_directory.name, _id),
                    partial_tag=partial_tag,
                    latest_tag=latest_tag
                )

    def cleanup(self):
        self.temp_directory.cleanup()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--proto-folder', required=True,  nargs='+')
    parser.add_argument('--repo-folder', type=str, required=True)
    parser.add_argument('--docker-repository', type=str, required=True)
    parser.add_argument('--prefix-tag', type=str, required=False, default="grpc-gateway-")
    parser.add_argument('--always-rebuild', action='store_true')

    args = parser.parse_args()

    builder = GrpcGatewayBuilder(
        repository_folder=args.repo_folder,
        docker_repository=args.docker_repository,
        prefix_tag=args.prefix_tag,
        always_rebuild=args.always_rebuild
    )

    builder.start(args.proto_folder)
    builder.cleanup()


if __name__ == "__main__":
    main()
