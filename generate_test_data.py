import pandas as pd

def create_sample_files():
    # --- File 1: Initial Baseline ---
    data_v1 = [
        {
            "internalid": "REQ_SYS_01",
            "content": "The system shall operate within -40C to +85C ambient temperature.",
            "parent_ids": ""  # Root level
        },
        {
            "internalid": "REQ_HW_01",
            "content": "The housing shall provide IP67 water and dust ingress protection.",
            "parent_ids": "REQ_SYS_01"
        },
        {
            "internalid": "REQ_SW_01",
            "content": "The firmware shall boot within 500ms after power-on reset.",
            "parent_ids": "REQ_SYS_01"
        },
    ]
    pd.DataFrame(data_v1).to_excel("requirements_v1.xlsx", index=False)
    print("Created 'requirements_v1.xlsx' (Baseline)")

    # --- File 2: Updated State (Run 2) ---
    data_v2 = [
        # Scenario 1: Untouched
        {
            "internalid": "REQ_SYS_01",
            "content": "The system shall operate within -40C to +85C ambient temperature.",
            "parent_ids": ""
        },
        # Scenario 2: Structural modification (add additional parent or relation)
        {
            "internalid": "REQ_HW_01",
            "content": "The housing shall provide IP67 water and dust ingress protection.",
            "parent_ids": "REQ_SYS_01"
        },
        # Scenario 3: Content edited -> Triggers revision on REQ_SW_01 and bubble-up to REQ_SYS_01
        {
            "internalid": "REQ_SW_01",
            "content": "The firmware shall boot within 250ms after power-on reset (accelerated boot).",
            "parent_ids": "REQ_SYS_01"
        },
        # Scenario 4: Brand new requirement -> Triggers creation and relinking to REQ_SYS_01
        {
            "internalid": "REQ_SW_02",
            "content": "The system shall log all boot failures to internal non-volatile EEPROM.",
            "parent_ids": "REQ_SYS_01"
        }
    ]
    pd.DataFrame(data_v2).to_excel("requirements_v2.xlsx", index=False)
    print("Created 'requirements_v2.xlsx' (Modified/New entries)")

if __name__ == "__main__":
    create_sample_files()
