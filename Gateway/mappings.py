measurand_mapping = {
    'active_power': {
        'measurand': 'Power.Active.Import',  # or 'Power.Active.Export' depending on your setup
        'unit': 'W'  # Watts
    },
    'powerfactor': {
        'measurand': 'Power.Factor',
        'unit': 'W'  # Typically unitless
    },
    'avg_current': {
        'measurand': 'Current.Import',
        'unit': 'A'  # Amperes
    },
    'voltage_ll': {
        'measurand': 'Voltage',
        'unit': 'V'  # Volts
    },
    'voltage_ln': {
        'measurand': 'Voltage',
        'unit': 'V'  # Volts
    },
    'frequency': {
        'measurand': 'Frequency',
        'unit': 'Hz'  # Hertz
    },
    # Add other mappings as needed:
    # e.g.
    'active_energy': {
        'measurand': 'Energy.Active.Import.Register',
        'unit': 'Wh'  # Watt-hour
    },
    'reactive_power': {
        'measurand': 'Power.Reactive.Import',
        'unit': 'VAR'  # Volt-ampere reactive
    },
    'temperature': {
        'measurand': 'Temperature',
        'unit': 'C'  # Celsius
    }
    ,
    'SoC': {
        'measurand': 'SoC',
        'unit': '%'  
    }
}
