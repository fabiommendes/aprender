# Aprender.unb.br

CLI interface to access the Moodle instance of the University of Brasilia (UnB).
With a few modifications (or maybe even without any), it can be used to access
other Moodle configurations.


## Installation

Use pip or any standard Python tooling to install it:

```bash
$ pip install aprender

# or maybe you prefer uvx or pipx
$ uv tool install aprender
```

My prefered way is to install [uv](http://astral.sh/uv/) and create an alias in 
.bashrc (or the equivalent) for your shell:

```bash
alias aprender='uvx aprender'
```

## Usage

Download the grades and/or submissions for an quiz in HTML. This is necessary
because Moodle corrupts the output in other formats like CSV and JSON by striping
whitespaces from essay submissions. 

Save the HTML file in the current directory and run:

```bash
$ aprender load
```

This will create a few csv files in the current directory with the parsed data.

For more options, as usual, `aprender --help` flag is your friend.

