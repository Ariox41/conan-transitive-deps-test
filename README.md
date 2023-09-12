# Conan transitive dependencies test

A test to reproduce the problem of handling transitive dependencies when using version ranges

## Usage

install conan 2 and execute command:

```shell
python3 ./test.py
```

The test sets the CONAN_HOME variable to a local directory, and should not have external side effects.
