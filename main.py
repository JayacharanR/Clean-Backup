from src.organiser import organise_files, print_summary
from src.duplicate_handler import handle_duplicates, print_duplicate_report
from src.undo_manager import undo_manager
import src.config

def main():
    source = None
    destination = None
    current_threshold = src.config.get_threshold()
    
    while True:
        print("\nClean-Backup: Photo & Video Organizer")
        print("-------------------------------------")
        print("\nOptions:")
        print("  [1] Organize files by date")
        print("  [2] Find duplicate images")
        print("  [3] Configure Duplicate Sensitivity")
        print("  [4] Undo Last Operation")
        print("  [Q] Quit")
        
        mode = input("\nSelect mode: ").strip().upper()
        
        if mode == "Q":
            break
            
        if mode == "4":
             print("\n--- Undo / Rollback ---")
             sessions = undo_manager.list_sessions()
             if not sessions:
                 print("No undo history found.")
                 continue
                 
             print("Available sessions:")
             for i, sess in enumerate(sessions):
                 print(f"  [{i+1}] Session {sess['id']} ({sess['count']} actions)")
             
             choice = input("\nSelect session to revert (or 'L' for Latest): ").strip().upper()
             
             target_session = None
             if choice == 'L' or choice == '':
                 target_session = sessions[0]
             elif choice.isdigit():
                 idx = int(choice) - 1
                 if 0 <= idx < len(sessions):
                     target_session = sessions[idx]
             
             if target_session:
                 confirm = input(f"Are you sure you want to revert {target_session['count']} actions from {target_session['id']}? (y/n): ")
                 if confirm.lower() == 'y':
                     undo_manager.undo_session(target_session['path'])
             else:
                 print("Invalid selection.")
             
             continue

        if mode == "3":
            print(f"==> Current Sensitivity Threshold (Active): {current_threshold}")
            print("\n--- Duplicate Detection Sensitivity ---")
            print("1. Exact Matches Only (Safe) -> Threshold: 0 (or 2 for slight compression artifacts)")
            print("2. Standard (Default) -> Threshold: 5 to 7 (Catches resized images, format changes)")
            print("3. Aggressive (Loose) -> Threshold: 10+ (Might catch burst photos or very heavy edits)")
            
            try:
                val = int(input("Enter custom Hamming distance threshold: ").strip())
                if val < 0:
                    print("❌ Threshold cannot be negative. Setting to 0.")
                    val = 0
                elif val > 25:
                    print("❌ Threshold too high (max 64). Setting to 15.")
                    val = 15
                
                current_threshold = val
                src.config.save_config("phash_threshold", val)
                print(f"✅ Sensitivity set to Threshold: {current_threshold} (Saved)")
            except ValueError:
                print("❌ Invalid input. Keeping current threshold.")
            continue
        
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
                        continue
                
                if action == "delete":
                    confirm = input("⚠️  This will DELETE files. Type 'yes' to confirm: ")
                    if confirm.lower() != 'yes':
                        print("Cancelled.")
                        continue
                
                print(f"\n⏳ Scanning for duplicates (Threshold: {current_threshold})...")
                report = handle_duplicates(source, duplicates_dir=duplicates_dir, action=action, threshold=current_threshold)
                print_duplicate_report(report)
                
                if report.duplicates_moved > 0:
                    action_word = "moved" if action == "move" else "copied" if action == "copy" else "deleted"
                    print(f"✅ {report.duplicates_moved} duplicate files {action_word}")
            # Loop back to menu instead of returning? 
            # Original code returned. I'll continue loop for better UX.
            continue
        
        if mode == "1":
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
                
                check_name_dups = input("Check for name-based duplicates (e.g., photo(1).jpg, Image copy.png)? (y/n): ").strip().lower()
                check_name_duplicates = (check_name_dups == 'y')
                
                if check_duplicates:
                    print(f"  Using Rust perceptual hashing to detect duplicate images (Threshold: {current_threshold})")
                
                if check_name_duplicates:
                    print(f"  Detecting OS duplicate patterns: (1), (copy), - Copy, copy, drag/drop numbers")
                
                stats = organise_files(source, destination, operation, check_duplicates=check_duplicates, duplicate_threshold=current_threshold, check_name_duplicates=check_name_duplicates)
                print_summary(stats, operation)
                
                print("Check logs for detailed information!")
            else:
                print("Source and Destination paths are required.")
            continue
            
        print("Invalid option. Please try again.")

if __name__ == "__main__":
    main()
