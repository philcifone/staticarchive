This repo is a work in progress and is for my personal use. Use at your own risk.

The below scripts are designed to be used inside a directory to create an index.html (or index-basic.html) to view the files neatly in your browser.

# build.py
Python build script - matches my style guide - riddled with javascript

# basicBuild.py
minimal build

# build.sh (not working)
bash build script


  bash build.sh                  # scan current directory                                          
  bash build.sh /path/to/folder  # scan a specific path                                            
  bash build.sh --serve          # build + start local server on :8080                           
                                                                                                   
  Key implementation notes:
                                                                                                   
  - Parallel arrays instead of Python dicts — E_NAME, E_PATH, E_TYPE, E_EXT, E_SIZE, E_MTIME hold  
  entry data                                                                                       
  - Portable stat — tries GNU stat -c first, falls back to BSD stat -f (macOS)                     
  - URL encoding — delegates to python3 -c for filenames with spaces/special chars; passes through 
  if python3 isn't available
  - HTML template — uses heredocs with 'HTMLEOF' (quoted = no expansion) for static parts and
  unquoted HTMLEOF for parts needing variable interpolation
  - Recursive build — saves subdirectory names before recursing since scan() overwrites the global
  arrays
  - The generated HTML output is identical to build.py

