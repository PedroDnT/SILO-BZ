#!/bin/bash

# Brazilian Financial Data APIs - Deployment Script
# This script helps deploy the APIs and documentation to Vercel

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Functions
print_header() {
    echo -e "${BLUE}================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}================================${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

# Check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Main script
main() {
    print_header "Brazilian Financial Data APIs - Deployment"
    
    # Check prerequisites
    print_info "Checking prerequisites..."
    
    if ! command_exists node; then
        print_error "Node.js is not installed. Please install Node.js 18+ first."
        exit 1
    fi
    print_success "Node.js is installed"
    
    if ! command_exists npm; then
        print_error "npm is not installed. Please install npm first."
        exit 1
    fi
    print_success "npm is installed"
    
    if ! command_exists python3; then
        print_error "Python 3 is not installed. Please install Python 3.9+ first."
        exit 1
    fi
    print_success "Python 3 is installed"
    
    # Check if Vercel CLI is installed
    if ! command_exists vercel; then
        print_warning "Vercel CLI is not installed."
        read -p "Do you want to install it now? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            npm install -g vercel
            print_success "Vercel CLI installed"
        else
            print_error "Vercel CLI is required. Please install it with: npm install -g vercel"
            exit 1
        fi
    else
        print_success "Vercel CLI is installed"
    fi
    
    # Check if logged in to Vercel
    print_info "Checking Vercel authentication..."
    if ! vercel whoami >/dev/null 2>&1; then
        print_warning "Not logged in to Vercel"
        print_info "Please log in to Vercel..."
        vercel login
    else
        print_success "Logged in to Vercel as $(vercel whoami)"
    fi
    
    # Ask deployment type
    echo
    print_header "Deployment Options"
    echo "1) Preview deployment (test before production)"
    echo "2) Production deployment"
    echo "3) Test APIs locally"
    echo "4) Test documentation locally"
    echo "5) Exit"
    echo
    read -p "Select an option (1-5): " option
    
    case $option in
        1)
            print_header "Preview Deployment"
            print_info "Deploying to preview environment..."
            vercel
            print_success "Preview deployment complete!"
            print_info "Test your deployment, then run this script again and select option 2 for production."
            ;;
        2)
            print_header "Production Deployment"
            print_warning "This will deploy to production!"
            read -p "Are you sure? (y/n) " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                print_info "Deploying to production..."
                vercel --prod
                print_success "Production deployment complete!"
                echo
                print_info "Your APIs are now live!"
                print_info "Next steps:"
                echo "  1. Test all endpoints"
                echo "  2. Deploy documentation to Mintlify"
                echo "  3. Configure custom domain (optional)"
                echo "  4. Set up monitoring"
            else
                print_info "Production deployment cancelled"
            fi
            ;;
        3)
            print_header "Test APIs Locally"
            print_info "Starting local API servers..."
            print_warning "This will start 3 servers on ports 8000, 8001, and 8002"
            print_info "Press Ctrl+C to stop all servers"
            echo
            
            # Check if ports are available
            if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null 2>&1; then
                print_error "Port 8000 is already in use"
                exit 1
            fi
            if lsof -Pi :8001 -sTCP:LISTEN -t >/dev/null 2>&1; then
                print_error "Port 8001 is already in use"
                exit 1
            fi
            if lsof -Pi :8002 -sTCP:LISTEN -t >/dev/null 2>&1; then
                print_error "Port 8002 is already in use"
                exit 1
            fi
            
            # Install dependencies if needed
            if [ ! -d ".venv" ]; then
                print_info "Creating virtual environment..."
                python3 -m venv .venv
            fi
            
            print_info "Installing dependencies..."
            source .venv/bin/activate
            pip install -q -r requirements.txt
            
            # Start servers in background
            print_info "Starting CVM API on port 8000..."
            uvicorn src.cvm_api.main:app --reload --port 8000 &
            CVM_PID=$!
            
            print_info "Starting B3 CALC API on port 8001..."
            uvicorn src.b3_calc_api.main:app --reload --port 8001 &
            B3_PID=$!
            
            print_info "Starting BACEN API on port 8002..."
            uvicorn src.bacen_api.main:app --reload --port 8002 &
            BACEN_PID=$!
            
            # Wait a bit for servers to start
            sleep 3
            
            print_success "All APIs are running!"
            echo
            print_info "API URLs:"
            echo "  CVM API:    http://localhost:8000"
            echo "  B3 CALC API: http://localhost:8001"
            echo "  BACEN API:   http://localhost:8002"
            echo
            print_info "Test endpoints:"
            echo "  curl http://localhost:8000/health"
            echo "  curl http://localhost:8002/api/v1/bacen/sgs/well-known"
            echo "  curl http://localhost:8001/api/v1/indexes"
            echo
            print_warning "Press Ctrl+C to stop all servers"
            
            # Wait for Ctrl+C
            trap "kill $CVM_PID $B3_PID $BACEN_PID 2>/dev/null; print_info 'Servers stopped'; exit 0" INT
            wait
            ;;
        4)
            print_header "Test Documentation Locally"
            
            # Check if Mintlify CLI is installed
            if ! command_exists mintlify; then
                print_warning "Mintlify CLI is not installed."
                read -p "Do you want to install it now? (y/n) " -n 1 -r
                echo
                if [[ $REPLY =~ ^[Yy]$ ]]; then
                    npm install -g mintlify
                    print_success "Mintlify CLI installed"
                else
                    print_error "Mintlify CLI is required. Please install it with: npm install -g mintlify"
                    exit 1
                fi
            fi
            
            print_info "Starting Mintlify dev server..."
            print_info "Documentation will be available at http://localhost:3000"
            print_warning "Press Ctrl+C to stop the server"
            echo
            mintlify dev
            ;;
        5)
            print_info "Exiting..."
            exit 0
            ;;
        *)
            print_error "Invalid option"
            exit 1
            ;;
    esac
}

# Run main function
main
