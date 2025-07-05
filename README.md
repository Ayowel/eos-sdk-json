# Epic Games EOS SDK API specifications

This projects provides Epic Games API specifications in a JSON file similar to Steam's API JSON file for easy interoperability layer generation with the C EOS SDK.

Releases use the latest SDK version available at the time of the release and the latest commit's hash at the time of the release.

In most cases, you should use the latest release or a fixed release version.

## Build a specification file

To build a specification file:

* Either manually download and unzip the desired C SDK in a local directory, or use `get_sdk.sh` to get the latest version:

```sh
# Requires curl and jq
./get_sdk.sh target
unzip -d target target/*.zip 'SDK/Include/*'
```

* Build the SDK's JSON representation:

```sh
./scripts/build.py target/SDK target/EOS_C_SDK-latest.json
```
