# Development instructions

## Run a test release workflow

### Pre-requisites

* [nektos/act](https://github.com/nektos/act) runner
* A PAT GitHub Token with **read** access to public repositories

### Run the test

The options in the following command may be put in your local ~/.config/act/actrc file (create it if it does not exist). It is recommended that you at least put your PAT token in there.

```sh
act -P ubuntu-latest="catthehacker/ubuntu:act-latest" \
    -s GITHUB_TOKEN="$GITHUB_PAT_TOKEN" \
    --artifact-server-path "$PWD/.artifacts" \
    -W ".github/workflows/release.yaml" \
    schedule
```
