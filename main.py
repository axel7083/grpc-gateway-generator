from typing import Optional

import time
import git
import tempfile
import argparse
from pathlib import Path
from os import path, remove, getcwd
from glob import glob
import shutil
import subprocess
import re
from string import Template
import docker


def diff_folder(repo, folder: str) -> bool:
    print(f"Getting repo {repo}")
    repo = git.Repo(repo)

    if folder.startswith("/"):
        folder = folder[1:]

    head = str(repo.commit("HEAD"))
    head_1 = str(repo.commit("HEAD~1"))
    print(f"Difference between {head} and {head_1}")

    return len(repo.git.diff(head, head_1, folder)) > 0


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


def generate(repo: str, protos: [str], output: str):
    print(f"Generating files in {output} for {len(protos)} files.")

    # Fetch all the files in the template dir
    template = glob(path.join(repo, "template", "*"))

    dest = path.join(output, "template")

    # Ensure the directory exist
    Path(output).mkdir(exist_ok=True)
    #
    Path(dest).mkdir(exist_ok=True)

    # Copy Dockerfile
    shutil.copyfile(path.join(repo, "Dockerfile"), path.join(output, "Dockerfile"))

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


def build_docker_images(output: str, ids: [str], repository: str) -> [str]:
    # init docker
    client = docker.from_env()

    for _id in ids:
        build_dir = path.join(output, _id)
        if not Path(build_dir).is_dir():
            print(f"The path {build_dir} is supposed to be a dir. Therefore skiping.")
            continue

        tag = "grpc-gateway-" + (_id.replace(".", "-")) + "-" + str(int(time.time()))
        image, _ = client.images.build(
            path=build_dir,
            dockerfile="Dockerfile",
            buildargs={"project": "template"},
            tag=repository + ":" + tag
        )

        client.images.push(repository=repository, tag=tag)
        print(f"Image {repository}:{tag} pushed.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--proto-folder', required=True,  nargs='+')
    parser.add_argument('--repo-folder', type=str, required=True)
    parser.add_argument('--docker-repository', type=str, required=True)
    parser.add_argument('--rebuild-all', action='store_true')

    args = parser.parse_args()

    output = tempfile.TemporaryDirectory().name

    if not Path(args.repo_folder).exists():
        raise Exception("The repository folder does not exist.")


    ids = []
    for folder in args.proto_folder:

        absolute_path = path.join(args.repo_folder, folder)
        if not Path(absolute_path).exists():
            raise Exception("The folder " + folder + " does not exist in the repository given.")

        if not args.rebuild_all:
            # If not difference with the previous commit we pass
            if not diff_folder(args.repo_folder, folder):
                print(folder + " no diff.")
                continue
            else:
                print(f"Folder {folder} will be rebuild.")

        protos = get_protos(absolute_path)
        if len(protos) == 0:
            raise Exception("The folder given do not have any .proto files.")

        # Ensure the directory exist
        Path(output).mkdir(exist_ok=True)

        _id = folder[len(path.dirname(folder)) + 1:]
        generate(args.repo_folder, protos, path.join(output, _id))
        ids.append(_id)

    build_docker_images(output, ids, args.docker_repository)


if __name__ == "__main__":

    main()
