from src.organiser import organise_files, print_summary
from src.duplicate_handler import handle_duplicates, print_duplicate_report

def main():
    source = None
    destination = None
    while (not source and not destination):
        print("Clean-Backup: Photo & Video Organizer")
        print("-------------------------------------")
        print("\nOptions:")
        print("  [1] Organize files by date")
        print("  [2] Find duplicate images")
        
        mode = input("\nSelect mode (1/2): ").strip()
        
        if mode == "2":
            # Duplicate detection only (Rust-powered)
            source = input("Enter folder to scan for duplicates: ").strip()
            if source:
                print("\nDuplicate handling options:")
                print("  [R] Report only (no changes)")
                print("  [M] Move duplicates to folder")
                print("  [C] Copy duplicates to folder (keeps originals)")
                print("  [D] Delete duplicates (keeps best)")
                
                action_choice = input("Select action (R/M/C/D): ").strip().upper()
                action_map = {"R": "report", "M": "move", "C": "copy", "D": "delete"}
                action = action_map.get(action_choice, "report")
                
                duplicates_dir = None
                if action in ("move", "copy"):
                    duplicates_dir = input("Enter destination folder for duplicates: ").strip()
                    if not duplicates_dir:
                        print("❌ Destination folder is required. Aborting.")
                        return
                
                if action == "delete":
                    confirm = input("⚠️  This will DELETE files. Type 'yes' to confirm: ")
                    if confirm.lower() != 'yes':
                        print("Cancelled.")
                        return
                
                print("\n⏳ Scanning for duplicates (using Rust perceptual hashing)...")
                report = handle_duplicates(source, duplicates_dir=duplicates_dir, action=action)
                print_duplicate_report(report)
                
                if report.duplicates_moved > 0:
                    action_word = "moved" if action == "move" else "copied" if action == "copy" else "deleted"
                    print(f"✅ {report.duplicates_moved} duplicate files {action_word}")
            return
        
        source = input("Enter source folder path: ")
        destination = input("Enter destination folder path: ")
        
        if source and destination:
            # Ask user for move or copy preference
            print("\nChoose operation:")
            print("  [M] Move files (removes from source)")
            print("  [C] Copy files (keeps originals)")
            choice = None
            while(choice!='C' and choice!='M'):
                choice=input("Enter choice (M/C): ").strip().upper()
                
                if choice == 'C':
                    operation = 'copy'
                else:
                    operation = 'move'
            
            # Ask about duplicate detection
            check_dups = input("\nCheck for perceptual duplicates before organizing? (y/n): ").strip().lower()
            check_duplicates = (check_dups == 'y')
            
            if check_duplicates:
                print("  Using Rust perceptual hashing to detect duplicate images")
            
            stats = organise_files(source, destination, operation, check_duplicates=check_duplicates)
            print_summary(stats, operation)
            
            print("Check logs for detailed information!")
        else:
            print("Source and Destination paths are required.")

if __name__ == "__main__":
    main()
