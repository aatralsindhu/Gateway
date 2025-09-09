# IH_Gateway Project

## Overview
IH_Gateway is a Django project designed to serve as a gateway application. It includes a dedicated app named Gateway, which handles various functionalities.

## Project Structure
```
IH_Gateway/
├── Gateway/                # The main application directory
│   ├── __init__.py        # Marks the Gateway directory as a Python package
│   ├── admin.py           # Admin site configuration
│   ├── apps.py            # App configuration
│   ├── migrations/         # Database migrations
│   │   └── __init__.py    # Marks migrations directory as a Python package
│   ├── models.py          # Data models for the app
│   ├── tests.py           # Test cases for the app
│   └── views.py           # View functions and classes
├── IH_Gateway/             # Project configuration directory
│   ├── __init__.py        # Marks the IH_Gateway directory as a Python package
│   ├── asgi.py            # ASGI configuration
│   ├── settings.py        # Project settings and configuration
│   ├── urls.py            # URL routing
│   └── wsgi.py            # WSGI configuration
├── manage.py               # Command-line utility for the project
└── README.md               # Project documentation
```

## Setup Instructions
1. **Install Django**: Make sure you have Django installed in your environment. You can install it using pip:
   ```
   pip install django
   ```

2. **Create the Project**: If you haven't created the project yet, you can do so with the following command:
   ```
   django-admin startproject IH_Gateway
   ```

3. **Create the App**: To create the Gateway app, run:
   ```
   python manage.py startapp Gateway
   ```

4. **Configure Settings**: Add 'Gateway' to the `INSTALLED_APPS` list in `IH_Gateway/settings.py`.

5. **Run Migrations**: Apply the initial migrations with:
   ```
   python manage.py migrate
   ```

6. **Run the Development Server**: Start the server using:
   ```
   python manage.py runserver
   ```

## Usage
You can access the application by navigating to `http://127.0.0.1:8000/` in your web browser. 

## Contributing
Contributions are welcome! Please feel free to submit a pull request or open an issue for any enhancements or bug fixes.

## License
This project is licensed under the MIT License. See the LICENSE file for more details.

