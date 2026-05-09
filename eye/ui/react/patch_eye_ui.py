import os

def patch_file(file_path):
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return False
        
    print(f"Patching {file_path}...")
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
        
    # Polyfill and Layout Fix code
    patch_code = """
    <script>
      // Object.hasOwn polyfill for older QWebEngine versions
      if (!Object.hasOwn) {
        Object.defineProperty(Object, "hasOwn", {
          value: function(object, property) {
            return Object.prototype.hasOwnProperty.call(object, property);
          },
          configurable: true,
          enumerable: false,
          writable: true
        });
      }
    </script>
    <style>
      html, body, #root {
        height: 100% !important;
        margin: 0 !important;
        padding: 0 !important;
        overflow: hidden !important;
      }
    </style>
    """
    
    # Inject before </head>
    if "</head>" in content:
        # Check if already patched with the new version to avoid duplicates
        if "!important" not in content:
            new_content = content.replace("</head>", f"{patch_code}</head>")
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            print("Successfully patched with polyfill and layout fix.")
        else:
            print("File already appears to be patched with layout fix.")
        return True
    else:
        print("Could not find </head> tag.")
        return False

if __name__ == "__main__":
    dist_path = os.path.join(os.path.dirname(__file__), "dist", "index.html")
    patch_file(dist_path)
    
    template_path = os.path.join(os.path.dirname(__file__), "index.html")
    patch_file(template_path)
