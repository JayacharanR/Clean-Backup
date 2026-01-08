from src.organiser import organise_files

def main():
    source=None
    destination=None
    while (not source and not destination):
        print("Clean-Backup: Photo & Video Organizer")
        print("-------------------------------------")
        source = input("Enter source folder path: ")
        destination = input("Enter destination folder path: ")
        if source and destination:
            organise_files(source, destination)
            print("\nOrganization complete! Check logs for details.")
        else:
            print("Source and Destination paths are required.")

if __name__ == "__main__":
    main()
