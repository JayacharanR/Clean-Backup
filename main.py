from src.organiser import organise_files, print_summary

def main():
    source = None
    destination = None
    while (not source and not destination):
        print("Clean-Backup: Photo & Video Organizer")
        print("-------------------------------------")
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
            
            stats = organise_files(source, destination, operation)
            print_summary(stats, operation)
            print("Check logs for detailed information!")
        else:
            print("Source and Destination paths are required.")

if __name__ == "__main__":
    main()
